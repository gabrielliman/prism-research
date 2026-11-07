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

    def _set_state(self, state: ModelState):
        self.state = state
        self.state_since = time.time()

    def on_activate(self, memory_usage: MemoryUsage, gpu_id: Optional[int] = None):
        """Activation done (or answered only when done)."""
        self._set_state(ModelState.ACTIVE)
        self.memory_usage = memory_usage
        if gpu_id is not None:
            self.gpu_ids = [gpu_id]

    def on_activating(self, memory_usage: MemoryUsage, gpu_id: Optional[int] = None):
        """Activation sent; ACTIVE once the GPU scheduler reports the model loaded."""
        self._set_state(ModelState.ACTIVATING)
        self.memory_usage = memory_usage
        if gpu_id is not None:
            self.gpu_ids = [gpu_id]

    def on_activated(self):
        self._set_state(ModelState.ACTIVE)

    def on_deactivate(self, memory_usage: MemoryUsage):
        """Deactivation done (or answered only when done), or the model was lost."""
        self._set_state(ModelState.INACTIVE)
        self.memory_usage = memory_usage

    def on_deactivating(self, memory_usage: MemoryUsage):
        """Deactivation sent; INACTIVE once the GPU scheduler reports it done."""
        self._set_state(ModelState.DEACTIVATING)
        self.memory_usage = memory_usage


def _zero_memory() -> MemoryUsage:
    return MemoryUsage(total_used_memory=0.0, model_weights_memory=0.0, memory_pool_memory=0.0,
                       req_to_token_pool_memory=0.0, token_to_kv_pool_memory=0.0)


def apply_lifecycle_event(instances: List[ModelInstanceState], event: dict) -> List[ModelInstanceState]:
    """Apply a GPU scheduler event (constants.controller_events_key) to one model's instances; returns those that
    changed. Only the instance on the event's GPU in the matching transition moves, so a late event of an older
    transition (e.g. the source GPU of a migration) does not change a newer one."""
    kind, gpu_id, changed = event.get("event"), event.get("gpu_id"), []
    for instance in instances:
        if gpu_id not in instance.gpu_ids:
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


def expire_transitions(model_instance_state_dict: Dict[str, List[ModelInstanceState]], now: float,
                       timeout_s: float) -> List[ModelInstanceState]:
    """Instances ACTIVATING/DEACTIVATING for timeout_s with no event are assumed to have finished the transition
    (a lost event must not freeze an instance). Returns those moved."""
    moved = []
    for instances in model_instance_state_dict.values():
        for instance in instances:
            if instance.state not in (ModelState.ACTIVATING, ModelState.DEACTIVATING):
                continue
            if now - instance.state_since < timeout_s:
                continue
            if instance.state == ModelState.ACTIVATING:
                instance.on_activated()
            else:
                instance.on_deactivate(instance.memory_usage)
            moved.append(instance)
    return moved


def get_gpu_memory_usage(gpu_id: int) -> float:
    free_gpu_memory, _ = torch.cuda.mem_get_info(gpu_id)
    return free_gpu_memory / (1 << 30)
