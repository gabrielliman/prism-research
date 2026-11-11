import dataclasses
import enum
import time
from typing import Dict, List, Optional

import torch

from sglang.srt.managers.io_struct import MemoryUsage


class ModelState(enum.Enum):
    """The global controller's view of an instance (explicit since D45; before, only ACTIVE/INACTIVE were used).

    With the worker pool, /activate and /deactivate return as soon as the GPU scheduler has the request, so:
        INACTIVE   --ActivateAction sent-->              ACTIVATING
        ACTIVATING --GPU scheduler "model_activated"-->  ACTIVE
        ACTIVE / ACTIVATING --DeactivateAction sent-->   DEACTIVATING
        DEACTIVATING --GPU scheduler "model_deactivated"--> INACTIVE
        any        --GPU scheduler "model_lost"-->       INACTIVE
    Each command sent to the GPU scheduler carries a `rid` (the instance's `cmd_rid`), echoed in its events: only the
    events of the instance's current command move it (D59), so a late answer to an older command changes nothing.
    A transition with no event for LIFECYCLE_TIMEOUT_S is never assumed done (D59): an activation is cleaned up
    with a new deactivation (controller), a deactivation stays DEACTIVATING (not serving, as INACTIVE).
    (engines that answer only when done skip ACTIVATING/DEACTIVATING). The policies keep Prism's two-state view,
    `ModelInstanceState.serving`: ACTIVATING counts as active (its memory is promised, it receives requests) and
    DEACTIVATING as inactive (it may be activated again, as before D45)."""

    ACTIVE = enum.auto()
    INACTIVE = enum.auto()
    ACTIVATING = enum.auto()  # activation sent, weights not reported loaded yet
    DEACTIVATING = enum.auto()  # deactivation sent, not reported done yet


@dataclasses.dataclass
class ModelInstanceState:
    model_name: str
    model_path: str
    instance_idx: int
    gpu_ids: list[int]  # for tensor parallelism > 1
    state: ModelState
    memory_usage: MemoryUsage
    init_memory_pool_size: float
    num_vio_reqs: int = 0  # num of violated request in current window
    state_since: float = 0.0  # time of the last state change (0 = initial state)
    cmd_rid: Optional[str] = None  # rid of the last activate/deactivate sent (None = initial placement) (D59)

    # for priority scheduling
    req_freq: float = float("-inf")
    urgency: float = float("-inf")
    priority: float = float("-inf")

    def __post_init__(self):
        # TODO: tune the transmition speed
        speed = 6.0  # GB/s
        self.swap_in_time = self.memory_usage.model_weights_memory / speed
        self.swap_out_time = 0.0
        self.last_memory_pool_size: float = self.init_memory_pool_size

    def __str__(self):
        total_memory = (
            self.memory_usage.model_weights_memory
            + self.memory_usage.memory_pool_memory
        )
        return f"Instance {self.instance_idx}: {self.state.name}, memory usage: {total_memory:.2f} GB, gpu_ids: {self.gpu_ids}, init_memory_pool_size: {self.init_memory_pool_size if self.init_memory_pool_size is not None else 'N/A'} GB"

    @property
    def serving(self) -> bool:
        """Prism's two-state view used by the policies: active or being activated."""
        return self.state in (ModelState.ACTIVE, ModelState.ACTIVATING)

    def _set_state(self, state: ModelState, cmd_rid: Optional[str] = None):
        self.state = state
        self.state_since = time.time()
        if cmd_rid is not None:
            self.cmd_rid = cmd_rid

    def on_activate(self, memory_usage: MemoryUsage, gpu_id: Optional[int] = None, cmd_rid: Optional[str] = None):
        """Activation done (or answered only when done)."""
        self._set_state(ModelState.ACTIVE, cmd_rid)
        self.memory_usage = memory_usage
        if gpu_id is not None:
            self.gpu_ids = [gpu_id]

    def on_activating(self, memory_usage: MemoryUsage, gpu_id: Optional[int] = None,
                      cmd_rid: Optional[str] = None):
        """Activation sent; ACTIVE once the GPU scheduler reports the model loaded."""
        self._set_state(ModelState.ACTIVATING, cmd_rid)
        self.memory_usage = memory_usage
        if gpu_id is not None:
            self.gpu_ids = [gpu_id]

    def on_activated(self):
        self._set_state(ModelState.ACTIVE)

    def on_deactivate(self, memory_usage: MemoryUsage, cmd_rid: Optional[str] = None):
        """Deactivation done (or answered only when done), or the model was lost."""
        self._set_state(ModelState.INACTIVE, cmd_rid)
        self.memory_usage = memory_usage

    def on_deactivating(self, memory_usage: MemoryUsage, cmd_rid: Optional[str] = None):
        """Deactivation sent; INACTIVE once the GPU scheduler reports it done."""
        self._set_state(ModelState.DEACTIVATING, cmd_rid)
        self.memory_usage = memory_usage


def _zero_memory() -> MemoryUsage:
    return MemoryUsage(total_used_memory=0.0, model_weights_memory=0.0, memory_pool_memory=0.0,
                       req_to_token_pool_memory=0.0, token_to_kv_pool_memory=0.0)


def answers_current_command(instance: ModelInstanceState, event: dict) -> bool:
    """The event answers the instance's current command (D59). Events without a rid (older GPU schedulers) and
    instances without a command yet (initial placement) match, as before D59."""
    rid = event.get("rid")
    return rid is None or instance.cmd_rid is None or rid == instance.cmd_rid


def apply_lifecycle_event(instances: List[ModelInstanceState], event: dict) -> List[ModelInstanceState]:
    """Apply a GPU scheduler event (constants.controller_events_key) to one model's instances; returns those that
    changed. Only the instance on the event's GPU whose current command the event answers (D59) moves, and only
    from the matching transition, so a late event of an older command changes nothing."""
    kind, gpu_id, changed = event.get("event"), event.get("gpu_id"), []
    for instance in instances:
        if gpu_id not in instance.gpu_ids or not answers_current_command(instance, event):
            continue
        if kind == "model_activated" and instance.state == ModelState.ACTIVATING:
            instance.on_activated()
        elif kind == "model_deactivated" and instance.state == ModelState.DEACTIVATING:
            instance.on_deactivate(instance.memory_usage)
        elif kind == "model_lost" and instance.state != ModelState.INACTIVE:
            instance.on_deactivate(_zero_memory())
        else:
            continue
        changed.append(instance)
    return changed


def is_stale_event(instances: List[ModelInstanceState], event: dict) -> bool:
    """No instance of the model on the event's GPU has the event's command as its current one (D59)."""
    gpu_id = event.get("gpu_id")
    return not any(answers_current_command(i, event) for i in instances if gpu_id in i.gpu_ids)


def expired_transitions(model_instance_state_dict: Dict[str, List[ModelInstanceState]], now: float,
                        timeout_s: float) -> List[ModelInstanceState]:
    """Instances ACTIVATING or DEACTIVATING for timeout_s with no event for their command. Nothing is changed: a
    missing confirmation is not a success (D59). The controller cleans an activation up with a new deactivation;
    a deactivation stays DEACTIVATING (the policies already see it as inactive)."""
    return [instance for instances in model_instance_state_dict.values() for instance in instances
            if instance.state in (ModelState.ACTIVATING, ModelState.DEACTIVATING)
            and now - instance.state_since >= timeout_s]


def get_gpu_memory_usage(gpu_id: int) -> float:
    free_gpu_memory, _ = torch.cuda.mem_get_info(gpu_id)
    return free_gpu_memory / (1 << 30)
