import logging
import os
import time
from itertools import chain
from typing import Dict, List, Set, Tuple, Optional, DefaultDict
from collections import defaultdict, deque

from sglang.multi_model.scheduling.decision_log import DecisionLog
from sglang.multi_model.scheduling.estimators import activation_cost, load_rotation_table, rotation_cost
from sglang.multi_model.scheduling.policy import deadline, structural
from sglang.multi_model.scheduling.action import (
    ActivateAction,
    BaseAction,
    DeactivateAction,
    ResizeAction,
)
from sglang.multi_model.scheduling.model_queue_tracker import ModelQueueTracker, Req, ReqState
from sglang.multi_model.scheduling.policy.base_global import GlobalPolicy
from sglang.multi_model.scheduling.state import ModelInstanceState, ModelState
from sglang.multi_model.scheduling.gpu.request_queue import RequestQueue
from sglang.srt.utils import get_available_gpu_memory
import itertools

logger = logging.getLogger(__name__)


class RequestViolationTracker:

    def __init__(self, window_size_seconds=10):
        self.window_size = window_size_seconds
        self.model_request_history = defaultdict(list)  # Dict[model_name, List[Tuple[timestamp, req]]]
    
    def update_request_history(self, model_queues: Dict[str, ModelQueueTracker]):
        current_time = time.time()
        
        for model_name, queue in model_queues.items():
            all_reqs = list(queue.running_reqs) + list(queue.waiting_reqs)
            
            self.model_request_history[model_name] = [
                (ts, req) for ts, req in self.model_request_history[model_name] 
                if current_time - ts <= self.window_size
            ]
            
            for req in all_reqs:
                self.model_request_history[model_name].append((current_time, req))
    
    def get_model_violation_stats(self, model_name: str) -> Tuple[int, float, int]:
        """violated_reqs_count, violation_proportion, total_reqs)"""

        current_time = time.time()
        history = self.model_request_history.get(model_name, [])
        
        recent_history = [(ts, req) for ts, req in history if current_time - ts <= self.window_size]
        
        if not recent_history:
            return (0, 0.0, 0)
        
        violated_reqs = sum(1 for _, req in recent_history 
                           if req.remaining_time_budget is not None and req.remaining_time_budget <= 0)
        total_reqs = len(recent_history)
        violation_proportion = violated_reqs / total_reqs if total_reqs > 0 else 0.0
        
        return (violated_reqs, violation_proportion, total_reqs)


class RequestMemoryTracker:
    def __init__(self, gpu_mem: float, model_weights_info: Dict[str, Dict[str, float]], window_size_seconds=10):
        self.window_size = window_size_seconds
        self.gpu_memory_request_history = defaultdict(list)
        self.model_weights_info = model_weights_info
        self.gpu_mem = gpu_mem
    
    def update_memory_history(self, 
                              gpu_to_model_mapping: Dict[int, List[str]], 
                              model_queues: Dict[str, ModelQueueTracker],
                              gpu_available_memory: Dict[int, float],
                              model_weights_info: Dict[str, Dict[str, float]],
                              total_gpu_memory: float):
        current_time = time.time()
        
        for gpu_id in self.gpu_memory_request_history:
            self.gpu_memory_request_history[gpu_id] = [
                entry for entry in self.gpu_memory_request_history[gpu_id]
                if current_time - entry[0] <= self.window_size
            ]
        
        for gpu_id, model_names in gpu_to_model_mapping.items():
            total_model_memory = 0
            total_reqs = 0
            
            for model_name in model_names:
                total_model_memory += model_weights_info[model_name]["model_size"]
                queue = model_queues.get(model_name)
                if queue:
                    total_reqs += len(queue.running_reqs) + queue.get_num_waiting_reqs()
            
            memory_available_for_requests = total_gpu_memory - total_model_memory
            
            memory_per_request = memory_available_for_requests / max(1, total_reqs)
            
            self.gpu_memory_request_history[gpu_id].append((current_time, memory_per_request, total_reqs))
    
    def get_gpu_memory_stats(self, gpu_id: int, gpu_to_model_mapping: Dict[int, List[str]]) -> Tuple[float, int]:
        """Returns (avg_memory_per_request, avg_total_reqs) over the time window"""
        model_names = gpu_to_model_mapping.get(gpu_id)
        total_memory_weight = sum([self.model_weights_info[model_name]["model_size"] for model_name in model_names])

        current_time = time.time()
        history = self.gpu_memory_request_history.get(gpu_id)
        
        recent_history = [(ts, memory, reqs) for ts, memory, reqs in history 
                          if current_time - ts <= self.window_size]
        
        if not recent_history:
            return (self.gpu_mem - total_memory_weight, 0)
        
        total_memory_weight = sum(reqs * memory for _, memory, reqs in recent_history)
        total_reqs = sum(reqs for _, _, reqs in recent_history)
        
        if total_reqs == 0:
            return (self.gpu_mem - total_memory_weight, 0)
        
        avg_memory_per_req = total_memory_weight / total_reqs
        avg_reqs = total_reqs / len(recent_history)
        
        return (avg_memory_per_req, avg_reqs)


class ModelRequestTracker:
    def __init__(self, window_size_seconds=10):
        self.window_size = window_size_seconds
        self.model_request_history = defaultdict(list)  # Dict[model_name, List[Tuple[timestamp, num_requests]]]
    
    def update_request_history(self, model_queues: Dict[str, ModelQueueTracker]):
        current_time = time.time()
        
        for model_name, queue in model_queues.items():
            cur_num_requests = len(queue.running_reqs) + queue.get_num_waiting_reqs()
            
            # Remove old entries
            self.model_request_history[model_name] = [
                (ts, reqs) for ts, reqs in self.model_request_history[model_name] 
                if current_time - ts <= self.window_size
            ]
            
            # Add new entry
            self.model_request_history[model_name].append((current_time, cur_num_requests))
    
    def get_model_request_stats(self, model_name: str) -> float:
        """Returns the average number of requests over the time window"""
        current_time = time.time()
        history = self.model_request_history.get(model_name, [])
        
        recent_history = [(ts, reqs) for ts, reqs in history if current_time - ts <= self.window_size]
        
        if not recent_history:
            return 0.0
        
        total_requests = sum(reqs for _, reqs in recent_history)
        return total_requests / len(recent_history)


class SimpleGlobalPolicy(GlobalPolicy):
    def __init__(
        self,
        num_gpus: int,
        gpu_mem: float,
        model_weights_info: Dict[str, Dict[str, float]],
        workers_per_gpu: int,
    ):
        self.num_gpus = num_gpus
        # assume all GPUs have the same maximal usable memory size
        self.gpu_mem = gpu_mem
        self.model_weights_info = model_weights_info
        self.workers_per_gpu = workers_per_gpu
        self.first_request_time = None
        self.model_last_active_time = {}
        
        self.request_history = RequestViolationTracker(window_size_seconds=3)
        self.memory_history = RequestMemoryTracker(gpu_mem, model_weights_info, window_size_seconds=30)
        self.model_request_tracker = ModelRequestTracker(window_size_seconds=30)

        self.MEMORY_POOL_BUDGET = 6

        # seconds without requests before an active model is evicted (PRISM_IDLE_THRESHOLD, default 50)
        self.MODEL_IDLE_THRESHOLD = float(os.environ.get("PRISM_IDLE_THRESHOLD", 50))
        # Eviction strategy (PRISM_EVICTION):
        #   idle      Prism's original: an active model is only evicted after MODEL_IDLE_THRESHOLD idle seconds
        #   pressure  also, when an inactive model with requests does not fit, evict the least recently used
        #             model idle for at least PRISM_PRESSURE_MIN_IDLE s (no waiting/running requests)
        #   adaptive  per-model idle threshold: PRISM_ADAPTIVE_K x the p90 of the model's own inter-arrival gaps
        #             (in [PRISM_ADAPTIVE_MIN, MODEL_IDLE_THRESHOLD]); under pressure, evict the idle model most
        #             overdue relative to its threshold
        #   fair      pressure, plus: when a model with requests has waited PRISM_FAIR_QUANTUM s and no model is
        #             idle, rotate out the model active for longest (at least PRISM_FAIR_QUANTUM s), even if busy
        #   throughput  swap by tokens/s per GB: when a model with requests does not fit, evict the active models
        #             (active for at least PRISM_SWAP_MIN_RESIDENCY s) serving the fewest tokens/s per GB they
        #             occupy, if the waiting model's token demand, aged by its wait (PRISM_SWAP_AGING_S), beats
        #             their tokens/s by PRISM_SWAP_MARGIN. Victims return their not-yet-started requests to the
        #             model's queue and either preempt the running ones (PRISM_SWAP_PREEMPT=1: recomputed later)
        #             or let them finish, without a time limit (PRISM_SWAP_PREEMPT=0). The timed drain
        #             (PRISM_SWAP_DRAIN) was removed (D30).
        #   edf       F6a/A2.1: which inactive model enters, and which active models leave for it, by deadline slack
        #             (EDF between models); policy/deadline.py edf_select. Knobs PRISM_EDF_FLOOR, PRISM_EDF_BUDGET.
        #   lvf       F6a/A9.1: by SuperInfer's virtual lag time (largest lag first); policy/deadline.py lvf_select.
        #             Knobs PRISM_LVF_ALPHA, PRISM_LVF_BETA_F, PRISM_LVF_BETA_B, PRISM_LVF_BUDGET.
        #             PRISM_LVF_COST_AWARE=1: A9.2, residency-aware lag with the measured swap cost (PRISM_LVF_MARGIN).
        #             Both: victims are deactivated as the throughput swap's (PRISM_SWAP_PREEMPT),
        #             only after PRISM_MIN_RESIDENCY s resident (A1.3), and a model needs PRISM_KV_RESERVE_REQS
        #             requests' worth of KV on top of its weights to be activated (A1.1). The idle eviction (step 1)
        #             still runs.
        self.EVICTION = os.environ.get("PRISM_EVICTION", "idle")
        #   loss      F6.16/A3.1: expected deadline loss (policy/deadline.py loss_select), PRISM_LOSS_THETA (0).
        #   value     F6.16/A10.1: throughput swap restricted to waiting models with a request that can still meet its
        #             TTFT deadline after a real swap (Ĉ_rot); the rest as `throughput`.
        assert self.EVICTION in ["idle", "pressure", "adaptive", "fair", "throughput", "edf", "lvf", "loss", "value"]
        # F6a knobs (D25). Defaults keep every other strategy unchanged: A1.1 and A1.3 are off unless set.
        self.EDF_FLOOR = float(os.environ.get("PRISM_EDF_FLOOR", 0))  # s; slack below it = request already lost
        self.EDF_BUDGET = int(os.environ.get("PRISM_EDF_BUDGET", 1))  # rotations in flight at once
        self.LVF_ALPHA = float(os.environ.get("PRISM_LVF_ALPHA", 3))
        self.LVF_BETA_F = float(os.environ.get("PRISM_LVF_BETA_F", 0.5))
        self.LVF_BETA_B = float(os.environ.get("PRISM_LVF_BETA_B", 0))
        self.LVF_BUDGET = int(os.environ.get("PRISM_LVF_BUDGET", 1))  # rotations in flight at once
        # F4 structural constraints (policy/structural.py), for every PRISM_EVICTION strategy; all off by default.
        self.KV_RESERVE_REQS = float(os.environ.get("PRISM_KV_RESERVE_REQS", 0))  # A1.1 b (0 = off)
        # A1.1 also keeps the part of the GPU kvcached never maps for KV free (GPU_UTILIZATION = 0.95 in
        # kvcached/slab_allocator.py); only with A1.1 on, so the default rule is unchanged.
        self.KV_FLOOR_FRAC = float(os.environ.get("PRISM_KV_FLOOR_FRAC", 0.05))
        self.KV_FLOOR_GB = self.KV_FLOOR_FRAC * gpu_mem if self.KV_RESERVE_REQS > 0 else 0.0
        self.MIN_RESIDENCY = float(os.environ.get("PRISM_MIN_RESIDENCY", 0))  # A1.3 T_min in s (0 = off)
        self.DEADLOCK_S = float(os.environ.get("PRISM_DEADLOCK_S", 0))  # A1.2 Δ_imp in s (0 = off)
        self.deadlock = structural.DeadlockDetector(self.DEADLOCK_S)
        # Ĉ_at = a + b·weights_gb + c·activations ahead (F2.3, reports/data/F02/cat/cat_model.json) and prefill
        # p̂ = a + b·tokens (F2.10, reports/registro/latencia_ref.json, Llama-3.1-8B)
        self.CAT_COEF = {"a": float(os.environ.get("PRISM_CAT_A", 0.4626)),
                         "b": float(os.environ.get("PRISM_CAT_B", 0.06277)),
                         "c": float(os.environ.get("PRISM_CAT_C", 1.1445))}
        self.PREFILL_A = float(os.environ.get("PRISM_PREFILL_A", 0.01228))
        self.PREFILL_B = float(os.environ.get("PRISM_PREFILL_B", 3.342e-05))
        self.SWAP_MARGIN = float(os.environ.get("PRISM_SWAP_MARGIN", 0.2))
        self.SWAP_MIN_RESIDENCY = float(os.environ.get("PRISM_SWAP_MIN_RESIDENCY", 20))
        self.SWAP_AGING_S = float(os.environ.get("PRISM_SWAP_AGING_S", 30))
        self.SWAP_PREEMPT = os.environ.get("PRISM_SWAP_PREEMPT", "0") == "1"
        # A9.2 (F6, 2026-11-09): residency-aware lag (policy/deadline.py _lvf_cost_aware), only with PRISM_EVICTION=lvf.
        # Ĉ_rot by weights from the F5.0a measurement (PRISM_CROT_FILE, default reports/registro/c_rot.json), with or
        # without preemption as PRISM_SWAP_PREEMPT; a missing table is an error, not a silent fallback.
        self.LVF_COST_AWARE = os.environ.get("PRISM_LVF_COST_AWARE", "0") == "1"
        self.LVF_MARGIN = float(os.environ.get("PRISM_LVF_MARGIN", 0))
        # F6.16 (D52, D53): A9.4 per-swap preemption (needs A9.2; the victims' default is no preemption, so
        # PRISM_SWAP_PREEMPT must stay 0), A2.3 predictive residency on A9.2, A3.1 threshold.
        self.LVF_PREEMPT = os.environ.get("PRISM_LVF_PREEMPT", "global")
        assert self.LVF_PREEMPT in ("global", "per_swap")
        self.LVF_PREEMPT_LAMBDA = float(os.environ.get("PRISM_LVF_PREEMPT_LAMBDA", 3.0))
        self.LVF_PREDICTIVE = os.environ.get("PRISM_LVF_PREDICTIVE", "0") == "1"
        self.LOSS_THETA = float(os.environ.get("PRISM_LOSS_THETA", 0))
        self.RATE_WINDOW_S = float(os.environ.get("PRISM_RATE_WINDOW_S", 60))  # A2.3 arrival-rate window
        if (self.LVF_PREEMPT == "per_swap" or self.LVF_PREDICTIVE) and not (self.EVICTION == "lvf" and self.LVF_COST_AWARE):
            raise ValueError("PRISM_LVF_PREEMPT=per_swap and PRISM_LVF_PREDICTIVE=1 need PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1")
        if self.LVF_PREEMPT == "per_swap" and self.SWAP_PREEMPT:
            raise ValueError("PRISM_LVF_PREEMPT=per_swap decides preemption per swap: leave PRISM_SWAP_PREEMPT=0")
        self.CROT_TABLE = self.CROT_P = self.CROT_NP = None
        if self.LVF_COST_AWARE or self.EVICTION in ("loss", "value"):
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))))
            path = os.environ.get("PRISM_CROT_FILE", os.path.join(root, "reports", "registro", "c_rot.json"))
            self.CROT_TABLE = load_rotation_table(path, self.SWAP_PREEMPT)
            self.CROT_P = load_rotation_table(path, True)
            self.CROT_NP = load_rotation_table(path, False)
            if self.CROT_TABLE is None:
                raise FileNotFoundError(f"PRISM_LVF_COST_AWARE=1 / PRISM_EVICTION=loss|value need the swap-cost table {path} (F5.0a)")
        for removed in ("PRISM_SWAP_DRAIN", "PRISM_SWAP_DRAIN_TIMEOUT"):
            if os.environ.get(removed, "0") not in ("", "0"):
                # an old suite would otherwise run a different configuration without noticing
                raise ValueError(f"{removed} was removed (D30): a swap now only chooses PRISM_SWAP_PREEMPT=0/1")
        self.SWAP_RESERVATION = 15.0  # s the swapped-in model keeps priority for the freed memory (timer mode)
        # How a swap reservation (the model victims were evicted for goes first on the freed memory and, in edf/lvf,
        # counts as a rotation in flight) ends (D45), PRISM_SWAP_RESERVATION_END:
        #   event  (default) when the model is activated (its memory is then counted as a pending activation) or has
        #          no waiting requests left, or after PRISM_SWAP_RESERVATION_MAX_S s (120) as a safety bound; no new
        #          rotation for it meanwhile. Without preemption a victim takes ~20 s (p50) to leave, longer than 15 s
        #          (F5.0a), so a fixed 15 s ran out before the memory was free.
        #   timer  before D45: after SWAP_RESERVATION s whatever happened.
        self.SWAP_RESERVATION_END = os.environ.get("PRISM_SWAP_RESERVATION_END", "event")
        assert self.SWAP_RESERVATION_END in ("event", "timer")
        self.SWAP_RESERVATION_MAX_S = float(os.environ.get("PRISM_SWAP_RESERVATION_MAX_S", 120))
        self.DEMAND_WINDOW = 30.0  # s over which a waiting model's queued tokens count as its demand
        self.served_history: DefaultDict[str, deque] = defaultdict(deque)  # (time, served_tokens) per model
        self.served_tput: Dict[str, float] = {}  # tokens/s each active model served over DEMAND_WINDOW
        self.swap_reservation_until: Dict[str, float] = {}
        self.swap_reservation_start: Dict[str, float] = {}  # F5.0f: when each reservation was made
        self._reservation_logged: Set[Tuple[str, float]] = set()  # (model, until) already reported as lapsed
        self.PRESSURE_MIN_IDLE = float(os.environ.get("PRISM_PRESSURE_MIN_IDLE", 2))
        self.PRESSURE_COOLDOWN = float(os.environ.get("PRISM_PRESSURE_COOLDOWN", 10))  # s between evictions for one model
        self.ADAPTIVE_K = float(os.environ.get("PRISM_ADAPTIVE_K", 3))
        self.ADAPTIVE_MIN = float(os.environ.get("PRISM_ADAPTIVE_MIN", 5))
        self.FAIR_QUANTUM = float(os.environ.get("PRISM_FAIR_QUANTUM", 30))
        # GB required on top of the weights to activate a model, so that its first KV pages fit
        self.ACTIVATION_HEADROOM = float(os.environ.get("PRISM_ACTIVATION_HEADROOM_GB", 0))
        # Activation accounting (PRISM_ACTIVATION_ACCOUNTING, default on; 0 = Prism as published). An activated
        # model's weights reach the GPU 1-20 s after the decision (the model service loads one model at a time),
        # so free memory measured meanwhile still counts them as free and later cycles promised the same memory
        # to other models. Pending activations (decided, not yet reported done by the GPU scheduler) are
        # subtracted from the measured free memory, and each activation also needs ACTIVATION_KV_GB for the KV
        # pages kvcached maps at activation.
        self.ACTIVATION_ACCOUNTING = os.environ.get("PRISM_ACTIVATION_ACCOUNTING", "1") == "1"
        self.ACTIVATION_KV_GB = 1.0 if self.ACTIVATION_ACCOUNTING else 0.0
        self.PENDING_ACTIVATION_TIMEOUT_S = 120.0
        self.pending_activations: Dict[Tuple[str, int], Tuple[float, float]] = {}  # (model, gpu) -> (GB, since)
        self.arrival_gaps: DefaultDict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self.model_idle_time: Dict[str, float] = {}
        self.model_has_requests: Dict[str, bool] = {}
        self.active_since: Dict[str, float] = {}
        self.pressure_cooldown_until: Dict[str, float] = {}
        self.VIOLATION_PROPORTION_THRESHOLD = 0.1 # 10%
        self.MEMORY_PER_REQUEST_RATIO_THRESHOLD = 15

        self.migrate_policy = "memory_per_request"
        self.dlog = DecisionLog()  # F2.1: JSON line per cycle with PRISM_DECISION_LOG=<path>; off by default
        assert self.migrate_policy in ["violation", "memory_per_request"]

    def _update_req_remaining_time_budget(
        self,
        model_queues: Dict[str, ModelQueueTracker]
    ):

        cur_time = time.time()

        for model_name, queue in model_queues.items():
            for req in queue.running_reqs + list(queue.waiting_reqs):
                if req.arrival_time is None or req.slo is None:
                    continue
                elapsed_time = cur_time - req.arrival_time
                req.remaining_time_budget = req.slo - elapsed_time

    def _calculate_model_avg_remaining_time_budget(
        self,
        model_name: str,
        model_queues: Dict[str, ModelQueueTracker]
    ) -> float:
        """Calculate the total remaining time budget for a model's request queue"""
        queue = model_queues.get(model_name)
        if not queue:
            return 0.0
            
        total_budget = 0.0
        all_reqs = list(queue.running_reqs) + list(queue.waiting_reqs)
        
        for req in all_reqs:
            if req.remaining_time_budget is not None:
                total_budget += req.remaining_time_budget
                
        return total_budget / len(all_reqs) if len(all_reqs) > 0 else float('inf')

    def _get_gpu_to_active_instances(
        self,
        model_instance_state_dict: Dict[str, List[ModelInstanceState]]
    ) -> Dict[int, List[ModelInstanceState]]:
        """Create a helper data structure that map a GPU ID to its active model instances."""

        gpu_to_active_instances: Dict[int, List[ModelInstanceState]] = dict()
        for gpu_id in range(self.num_gpus):
            gpu_to_active_instances[gpu_id] = []

        for model_name, instances in model_instance_state_dict.items():
            model_active_instances = {}  # GPU ID -> list of active instances
            for instance in instances:
                if instance.serving:
                    for gpu_id in instance.gpu_ids:
                        if gpu_id not in model_active_instances:
                            model_active_instances[gpu_id] = []
                        model_active_instances[gpu_id].append(instance)

            assert len(model_active_instances) <= 1
            
            if model_active_instances:
                gpu_id = list(model_active_instances.keys())[0]
                gpu_to_active_instances[gpu_id].extend(model_active_instances[gpu_id])

        return gpu_to_active_instances
    
    def _check_idle_instance_eviction(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]]
    ) -> Dict[int, List[ModelInstanceState]]:
        """Check for idle model instances that haven't had requests for a defined threshold.
        Return a dict of evictable model instances.
        """
        evictable_instances: Dict[int, List[ModelInstanceState]] = dict()
        
        if self.first_request_time is None:
            for model_name, queue in model_queues.items():
                if queue.get_last_arrival_time() != float("-inf"):
                    self.first_request_time = queue.get_last_arrival_time()
                    logger.info(f"first request time: {self.first_request_time}")
                    self.model_last_active_time = {model_name: self.first_request_time for model_name in model_queues.keys()}
                    break
        
        if self.first_request_time is None:
            return evictable_instances
        
        idle_models = set()
        current_time = time.time()
        
        for model_name, queue in model_queues.items():
            last_arrival = queue.get_last_arrival_time()
            if last_arrival > self.first_request_time:
                prev = self.model_last_active_time.get(model_name)
                if prev is not None and self.first_request_time < prev < last_arrival:
                    self.arrival_gaps[model_name].append(last_arrival - prev)
                self.model_last_active_time[model_name] = last_arrival

            last_request_time = self.model_last_active_time.get(model_name)
            if last_request_time is not None:
                idle_time = current_time - last_request_time
                has_requests = queue.get_num_waiting_reqs() > 0 or queue.get_num_running_reqs() > 0
                self.model_idle_time[model_name] = idle_time
                self.model_has_requests[model_name] = has_requests

                if model_name in [instance.model_name for instances in gpu_to_active_instances.values() for instance in instances]:
                    logger.info(f"Model {model_name} has been idle for {idle_time:.2f} seconds, its own last request or global first request time is {last_request_time}")
                    logger.info(f"Model {model_name} has waiting/running requests: {has_requests}")
                
                # Only consider models as idle if they have been idle for long enough AND have no active requests
                if idle_time > self._idle_threshold(model_name) and not has_requests:
                    idle_models.add(model_name)
        
        for gpu_id, active_instances in gpu_to_active_instances.items():
            if not active_instances:
                continue
            
            evictable_instances[gpu_id] = []
            
            for model_instance in active_instances:
                if model_instance.model_name in idle_models and self._resident_long_enough(
                        model_instance.model_name, current_time):
                    evictable_instances[gpu_id].append(model_instance)
        
        return evictable_instances

    def _add_pending_activation(self, model_name: str, gpu_id: int):
        if self.ACTIVATION_ACCOUNTING:
            gb = self.model_weights_info[model_name]["model_size"]
            self.pending_activations[(model_name, gpu_id)] = (gb + self.ACTIVATION_KV_GB, time.time())

    def activation_done(self, model_name: str, gpu_id: int):
        """The GPU scheduler reported the activation finished (or the model lost): its memory is now measured."""
        self.pending_activations.pop((model_name, gpu_id), None)

    def _pending_activation_gb(self) -> Dict[int, float]:
        now = time.time()
        for key, (_, since) in list(self.pending_activations.items()):
            if now - since > self.PENDING_ACTIVATION_TIMEOUT_S:
                logger.warning(f"Pending activation {key} not reported after {now - since:.0f} s; dropped")
                del self.pending_activations[key]
        out: Dict[int, float] = defaultdict(float)
        for (_, gpu_id), (gb, _) in self.pending_activations.items():
            out[gpu_id] += gb
        return out

    def _idle_threshold(self, model_name: str) -> float:
        """Idle seconds before eviction: fixed, or (adaptive) from the model's recent inter-arrival gaps."""
        gaps = self.arrival_gaps.get(model_name)
        if self.EVICTION != "adaptive" or not gaps or len(gaps) < 5:
            return self.MODEL_IDLE_THRESHOLD
        p90 = sorted(gaps)[int(0.9 * (len(gaps) - 1))]
        return min(self.MODEL_IDLE_THRESHOLD, max(self.ADAPTIVE_MIN, self.ADAPTIVE_K * p90))

    @staticmethod
    def _oldest_wait(queue: ModelQueueTracker, now: float) -> float:
        arrivals = [r.arrival_time for r in queue.waiting_reqs if r.arrival_time is not None]
        return now - min(arrivals) if arrivals else 0.0

    def _pressure_evictions(
        self,
        unplaced_models: List[str],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]],
        taken: Set[Tuple[str, int]],
    ) -> List[Tuple[ModelInstanceState, int, str]]:
        """Victims that make room for inactive models with requests that did not fit (PRISM_EVICTION != idle).
        At most one victim per waiting model per PRESSURE_COOLDOWN; the waiting model is activated in a later
        cycle, once the victim's memory is free. Returns (instance, gpu_id, reason)."""
        now = time.time()
        candidates = [
            (gpu_id, inst)
            for gpu_id, insts in gpu_to_active_instances.items()
            for inst in insts
            if (inst.model_name, inst.instance_idx) not in taken and self._resident_long_enough(inst.model_name, now)
        ]
        victims = []
        for model_name in unplaced_models:
            if self.pressure_cooldown_until.get(model_name, 0) > now:
                continue
            idle = [
                c for c in candidates
                if not self.model_has_requests.get(c[1].model_name, True)
                and self.model_idle_time.get(c[1].model_name, 0) >= self.PRESSURE_MIN_IDLE
            ]
            pick, reason = None, None
            if idle:
                if self.EVICTION == "adaptive":  # most overdue relative to its own usual gap
                    score = lambda c: self.model_idle_time[c[1].model_name] / self._idle_threshold(c[1].model_name)
                else:  # least recently used
                    score = lambda c: self.model_idle_time[c[1].model_name]
                pick, reason = max(idle, key=score), f"pressure eviction for {model_name}"
            elif self.EVICTION == "fair" and self._oldest_wait(model_queues[model_name], now) >= self.FAIR_QUANTUM:
                busy = [c for c in candidates if now - self.active_since.get(c[1].model_name, now) >= self.FAIR_QUANTUM]
                if busy:
                    pick = max(busy, key=lambda c: now - self.active_since[c[1].model_name])
                    reason = f"fair rotation for {model_name}"
            if pick is not None:
                candidates.remove(pick)
                victims.append((pick[1], pick[0], reason))
                self.pressure_cooldown_until[model_name] = now + self.PRESSURE_COOLDOWN
        return victims

    def _model_memory(self, model_name: str, tokens: float) -> float:
        """GB a model occupies: its weights plus the KV cache of `tokens` tokens."""
        info = self.model_weights_info[model_name]
        return info["model_size"] + info["cell_size"] * tokens / (1 << 30)

    def _aged_demand(self, queue: ModelQueueTracker, now: float) -> float:
        """Token demand (tokens/s) of a waiting model: its queued tokens served over DEMAND_WINDOW, aged by its
        oldest request's wait (so a starved model eventually wins)."""
        backlog = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.waiting_reqs)
        return backlog / self.DEMAND_WINDOW * (1 + self._oldest_wait(queue, now) / self.SWAP_AGING_S)

    def _update_tput(self, model_queues: Dict[str, ModelQueueTracker], active_models: Set[str]):
        """Tokens/s each active model served over the last DEMAND_WINDOW (from the token counts its engine
        reports every second; the per-second rate alone is too noisy at one sample per cycle)."""
        now = time.time()
        for model_name in list(self.served_tput):
            if model_name not in active_models:
                del self.served_tput[model_name]
                self.served_history.pop(model_name, None)
        for model_name in active_models:
            hist = self.served_history[model_name]
            hist.append((now, model_queues[model_name].served_tokens))
            while len(hist) > 2 and now - hist[1][0] >= self.DEMAND_WINDOW:  # keep one sample at/before it
                hist.popleft()
            t0, n0 = hist[0]
            # until a window has passed since activation, divide by the window (no extrapolation)
            self.served_tput[model_name] = (hist[-1][1] - n0) / max(now - t0, self.DEMAND_WINDOW / 2)

    def _keep_value(self, name: str, queue: ModelQueueTracker) -> Tuple[float, float, float]:
        """What keeping an active model is worth (A0.3's criterion, also A1.2's): tokens/s it served over the
        window plus its own queued tokens over the window, per GB it occupies (weights + KV of its running
        requests). Returns (per GB, tokens/s, GB)."""
        tokens = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.running_reqs)
        mem = self._model_memory(name, tokens)
        backlog = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.waiting_reqs)
        tput = self.served_tput.get(name, 0.0) + backlog / self.DEMAND_WINDOW
        return tput / mem, tput, mem

    def _throughput_swaps(
        self,
        unplaced_models: List[str],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]],
        taken: Set[Tuple[str, int]],
        gpu_available_memory: Dict[int, float],
    ) -> List[Tuple[ModelInstanceState, int, str]]:
        """Swaps by tokens/s per GB (PRISM_EVICTION=throughput). For each inactive model with requests that did
        not fit (highest aged demand first), pick on one GPU the active models with the lowest tokens/s per GB
        until enough memory would be free, and evict them if the waiting model's aged demand beats their
        tokens/s by SWAP_MARGIN. Sorting by density keeps small models that serve little but occupy little.
        Returns (instance, gpu_id, reason)."""
        now = time.time()
        candidates: Dict[int, list] = defaultdict(list)  # gpu_id -> [(density, tput, mem, instance)]
        for gpu_id, insts in gpu_to_active_instances.items():
            for inst in insts:
                name = inst.model_name
                if (name, inst.instance_idx) in taken:
                    continue
                if now - self.active_since.get(name, now) < max(self.SWAP_MIN_RESIDENCY, self.MIN_RESIDENCY):
                    continue
                density, tput, mem = self._keep_value(name, model_queues[name])
                candidates[gpu_id].append((density, tput, mem, inst))
        for cands in candidates.values():
            cands.sort(key=lambda c: c[0])

        victims = []
        demand = {m: self._aged_demand(model_queues[m], now) for m in unplaced_models}
        for model_name in sorted(unplaced_models, key=lambda m: -demand[m]):
            if self.pressure_cooldown_until.get(model_name, 0) > now:
                continue
            if self.SWAP_RESERVATION_END == "event" and self._reserved(model_name, now):
                continue  # its victims are still leaving: wait for them instead of evicting more (D45)
            need = self._activation_need_gb(model_name, model_queues.get(model_name))
            best = None
            for gpu_id, cands in candidates.items():
                missing, freed, lost, picked = need - gpu_available_memory.get(gpu_id, 0.0), 0.0, 0.0, []
                for c in cands:
                    if freed >= missing:
                        break
                    picked.append(c)
                    freed += c[2]
                    lost += c[1]
                if freed >= missing and demand[model_name] > (1 + self.SWAP_MARGIN) * lost:
                    if best is None or lost < best[1]:
                        best = (gpu_id, lost, picked)
            if best is None:
                continue
            gpu_id, lost, picked = best
            for c in picked:
                candidates[gpu_id].remove(c)
                victims.append((c[3], gpu_id, f"throughput swap for {model_name}"))
                logger.info(
                    f"Throughput swap: {c[3].model_name} ({c[1]:.0f} tok/s, {c[2]:.1f} GB) out for {model_name} "
                    f"(aged demand {demand[model_name]:.0f} tok/s)"
                )
            self.pressure_cooldown_until[model_name] = now + self.SWAP_RESERVATION
            self._reserve(model_name, now)
        return victims

    def _has_viable(self, model_name: str, queue: Optional[ModelQueueTracker], now: float) -> bool:
        """A10.1: some waiting request of model_name can still meet its TTFT deadline after a real swap (Ĉ_rot)."""
        if queue is None:
            return False
        c_rot = rotation_cost(self.model_weights_info[model_name]["model_size"], self.CROT_TABLE)
        return any(r.slo is not None and r.arrival_time is not None and not r.is_warmup
                   and r.arrival_time + r.slo >= now + c_rot for r in queue.waiting_reqs)

    def _arrival_rate(self, queue: Optional[ModelQueueTracker], now: float) -> float:
        """A2.3: arrivals/s of the model over the last RATE_WINDOW_S s (all requests the controller received)."""
        if queue is None:
            return 0.0
        start = now - self.RATE_WINDOW_S
        n = sum(1 for r in queue.received_reqs.values()
                if not r.is_warmup and r.arrival_time is not None and r.arrival_time >= start)
        return n / self.RATE_WINDOW_S

    def _typical_slo(self, queue: Optional[ModelQueueTracker]) -> Optional[float]:
        """A2.3: median TTFT SLO of the model's received requests (None if it never had one)."""
        slos = sorted(r.slo for r in (queue.received_reqs.values() if queue else []) if r.slo is not None
                      and not r.is_warmup)
        return slos[len(slos) // 2] if slos else None

    def _reserve(self, model_name: str, now: float):
        """Start a swap reservation for model_name (victims were evicted for it)."""
        length = self.SWAP_RESERVATION if self.SWAP_RESERVATION_END == "timer" else self.SWAP_RESERVATION_MAX_S
        self.swap_reservation_until[model_name] = now + length
        self.swap_reservation_start[model_name] = now

    def _reserved(self, model_name: str, now: float) -> bool:
        return self.swap_reservation_until.get(model_name, 0) > now

    def _end_reservations(self, now: float, active_models: Set[str], model_queues: Dict[str, ModelQueueTracker]):
        """D45 (event mode): a reservation ends when its model is activated (being activated counts: its memory is
        then a pending activation) or no longer has waiting requests; the 120 s safety bound is its `until`, and
        _log_lapsed_reservations reports it if reached. Timer mode: untouched (they run out after 15 s)."""
        if self.SWAP_RESERVATION_END != "event":
            return
        for name in [n for n in self.swap_reservation_until if self._reserved(n, now)]:
            queue = model_queues.get(name)
            waiting = queue is not None and any(not r.is_warmup for r in queue.waiting_reqs)
            if name in active_models or not waiting:
                if not waiting and name not in active_models:
                    self.dlog.note("reservation_dropped", name, reserved_s=now - self.swap_reservation_start[name])
                del self.swap_reservation_until[name]
                self.swap_reservation_start.pop(name, None)

    def _calculate_model_violation_stats(
        self,
        model_queues: Dict[str, ModelQueueTracker],
    ) -> Dict[str, Tuple[int, float, int]]:
        """
        Returns a dict mapping model_name to (violated_reqs_count, violation_proportion, total_reqs).
        """
        self.request_history.update_request_history(model_queues)
        
        model_violation_stats = {}
        for model_name in model_queues.keys():
            model_violation_stats[model_name] = self.request_history.get_model_violation_stats(model_name)
            
        return model_violation_stats

    def _calculate_gpu_violation_stats(
        self,
        gpu_to_model_mapping: Dict[int, List[str]],
        model_violation_stats: Dict[str, Tuple[int, float, int]]
    ) -> Dict[int, Tuple[int, float, int]]:
        """Calculate violation statistics for all GPUs based on model mappings.
        Returns a dict mapping gpu_id to (violated_reqs_count, violation_proportion, total_reqs).
        """
        gpu_violation_stats = {}
        
        for gpu_id, model_names in gpu_to_model_mapping.items():
            violated_reqs = 0
            total_reqs = 0
            
            for model_name in model_names:
                if model_name in model_violation_stats:
                    violated_count, _, req_count = model_violation_stats[model_name]
                    violated_reqs += violated_count
                    total_reqs += req_count
            
            violation_proportion = violated_reqs / total_reqs if total_reqs > 0 else 0.0
            gpu_violation_stats[gpu_id] = (violated_reqs, violation_proportion, total_reqs)
        
        return gpu_violation_stats
    
    def _calculate_memory_per_request(
        self,
        gpu_to_model_mapping: Dict[int, List[str]],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_available_memory: Dict[int, float]
    ) -> Dict[int, Tuple[float, int]]:
        """Calculate memory per request for each GPU.
        Returns a dict mapping gpu_id to (memory_per_request, total_reqs).
        """
        # Update model request history
        self.model_request_tracker.update_request_history(model_queues)
        
        gpu_memory_per_request = {}
        
        for gpu_id, model_names in gpu_to_model_mapping.items():
            total_model_memory = 0
            total_reqs = 0
            
            for model_name in model_names:
                total_model_memory += self.model_weights_info[model_name]["model_size"]
                # Use smoothed average of requests from history
                total_reqs += self.model_request_tracker.get_model_request_stats(model_name)
            
            total_gpu_memory = self.gpu_mem
            memory_available_for_requests = total_gpu_memory - total_model_memory
            
            if total_reqs == 0:
                memory_per_request = memory_available_for_requests / 1
            else:
                memory_per_request = memory_available_for_requests / total_reqs
                
            gpu_memory_per_request[gpu_id] = (memory_per_request, total_reqs)
        
        return gpu_memory_per_request

    def _is_placement_stable_by_violation(self, gpu_violation_stats: Dict[int, Tuple[int, float, int]]) -> bool:
        """Check if the placement results in a stable state where violation differences are within threshold."""
        for high_gpu_id, (_, high_violation, _) in gpu_violation_stats.items():
            for low_gpu_id, (_, low_violation, _) in gpu_violation_stats.items():
                if high_gpu_id != low_gpu_id and high_violation - low_violation > self.VIOLATION_PROPORTION_THRESHOLD:
                    return False
        return True

    def _is_placement_stable_by_memory(self, gpu_memory_per_request: Dict[int, Tuple[float, int]]) -> bool:
        """Check if the placement results in a stable state where memory per request differences are within threshold."""
        for high_gpu_id, (high_memory, _) in gpu_memory_per_request.items():
            for low_gpu_id, (low_memory, _) in gpu_memory_per_request.items():
                if high_gpu_id != low_gpu_id:
                    ratio = high_memory / low_memory
                    if ratio > self.MEMORY_PER_REQUEST_RATIO_THRESHOLD:
                        return False
        return True

    def _get_gpu_to_model_mapping(
        self,
        model_instance_state_dict: Dict[str, List[ModelInstanceState]]
    ) -> Dict[int, List[str]]:
        """Create a mapping from GPU ID to list of active model names."""
        gpu_to_models = {gpu_id: [] for gpu_id in range(self.num_gpus)}
        
        for model_name, instances in model_instance_state_dict.items():
            for instance in instances:
                if instance.serving:
                    for gpu_id in instance.gpu_ids:
                        gpu_to_models[gpu_id].append(model_name)
        
        return gpu_to_models
    
    def _find_optimal_migrations_by_violation(
        self,
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_available_memory: Dict[int, float],
        model_violation_stats: Dict[str, Tuple[int, float, int]],
        gpu_to_model_mapping: Dict[int, List[str]]
    ) -> List[Tuple[str, int, int]]:
        """Find optimal migrations based on violation statistics."""
        gpu_violation_stats = self._calculate_gpu_violation_stats(
            gpu_to_model_mapping, model_violation_stats
        )

        for gpu_id, stats in gpu_violation_stats.items():
            logger.info(f"GPU {gpu_id}, violation_proportion: {stats[1]}, total_reqs: {stats[2]}")
            for model_name in gpu_to_model_mapping[gpu_id]:
                logger.info(f"  {model_name}, violation_proportion: {model_violation_stats[model_name][1]}, total_reqs: {model_violation_stats[model_name][2]}")
        
        if self._is_placement_stable_by_violation(gpu_violation_stats):
            logger.info("Placement is stable, no migrations needed")
            return []
        
        sorted_gpus = sorted(
            [(gpu_id, stats[1], stats[2]) for gpu_id, stats in gpu_violation_stats.items()],
            key=lambda x: x[1], 
            reverse=True
        )
        
        gpu_models_with_violations = {}
        for gpu_id in range(self.num_gpus):
            gpu_models_with_violations[gpu_id] = []
            for model_name in gpu_to_model_mapping.get(gpu_id, []):
                if model_name in model_violation_stats:
                    avg_budget = self._calculate_model_avg_remaining_time_budget(model_name, model_queues)
                    
                    gpu_models_with_violations[gpu_id].append(
                        (model_name, model_violation_stats[model_name][1], avg_budget)
                    )
            
            gpu_models_with_violations[gpu_id].sort(key=lambda x: (x[1], -x[2]))
        
        for high_idx in range(len(sorted_gpus)):
            high_gpu_id, high_violation, high_avg_budget = sorted_gpus[high_idx]
            
            if high_avg_budget == float('inf'):
                continue
            
            for low_idx in range(len(sorted_gpus)-1, high_idx, -1):
                low_gpu_id, low_violation, low_avg_budget = sorted_gpus[low_idx]
                
                if high_violation - low_violation < self.VIOLATION_PROPORTION_THRESHOLD:
                    break
                
                if not gpu_models_with_violations[high_gpu_id]:
                    continue
                
                # prioritize migrating models with fewer requests
                models_with_req_count = []
                for model_name, violation, avg_budget in gpu_models_with_violations[high_gpu_id]:
                    queue = model_queues.get(model_name)
                    model_reqs = 0
                    if queue:
                        model_reqs = len(queue.running_reqs) + queue.get_num_waiting_reqs()
                    models_with_req_count.append((model_name, violation, avg_budget, model_reqs))
                
                sorted_models = sorted(models_with_req_count, key=lambda x: x[3])
                
                for model_name, violation, avg_budget, model_reqs in sorted_models:
                    if model_reqs == 0:
                        continue
                        
                    instance_idx = None
                    for instance in model_instance_state_dict.get(model_name):
                        if instance.serving and high_gpu_id in instance.gpu_ids:
                            instance_idx = instance.instance_idx
                            break
                    
                    if instance_idx is None:
                        continue
                    
                    model_memory = self.model_weights_info[model_name]["model_size"]
                    if gpu_available_memory[low_gpu_id] < model_memory:
                        continue
                    
                    simulated_mapping = {gpu_id: models.copy() for gpu_id, models in gpu_to_model_mapping.items()}
                    simulated_mapping[high_gpu_id].remove(model_name)
                    simulated_mapping[low_gpu_id].append(model_name)
                    
                    simulated_stats = self._calculate_gpu_violation_stats(
                        simulated_mapping, model_violation_stats
                    )

                    logger.info(f"Migration Placement: model {model_name} (with {model_reqs} requests) from {high_gpu_id} to {low_gpu_id}")
                    for gpu_id, stats in simulated_stats.items():
                        logger.info(f"  Simulated GPU {gpu_id}, violation_proportion: {stats[1]}, total_reqs: {stats[2]}")
                    
                    if self._is_placement_stable_by_violation(simulated_stats):
                        return [(model_name, instance_idx, low_gpu_id)]
                    logger.info("Migration placement is not stable, continue")
        
        logger.info("No optimal migrations found")
        return []

    def _count_unstable_pairs(self, gpu_memory_per_request: Dict[int, Tuple[float, int]]) -> int:
        """Count the number of unstable GPU pairs where memory ratio exceeds threshold."""
        unstable_pairs = 0
        gpu_ids = list(gpu_memory_per_request.keys())
        
        for i in range(len(gpu_ids)):
            for j in range(i+1, len(gpu_ids)):
                gpu_i = gpu_ids[i]
                gpu_j = gpu_ids[j]
                mem_i, reqs_i = gpu_memory_per_request[gpu_i]
                mem_j, reqs_j = gpu_memory_per_request[gpu_j]
                
                if reqs_i == 0 and reqs_j == 0:
                    unstable_pairs += 1
                    continue
                    
                if reqs_i == 0:
                    mem_i = float('inf')
                if reqs_j == 0:
                    mem_j = float('inf')
                    
                ratio = max(mem_i, mem_j) / min(mem_i, mem_j) if min(mem_i, mem_j) > 0 else float('inf')
                
                if ratio > self.MEMORY_PER_REQUEST_RATIO_THRESHOLD:
                    unstable_pairs += 1
                    
        return unstable_pairs

    def _get_gpu_active_instance_count(
        self,
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]]
    ) -> Dict[int, int]:
        """Get the number of active instances per GPU."""
        return {gpu_id: len(instances) for gpu_id, instances in gpu_to_active_instances.items()}

    def _find_optimal_migrations_by_memory(
        self,
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_available_memory: Dict[int, float],
        gpu_to_model_mapping: Dict[int, List[str]]
    ) -> List[Tuple[str, int, int]]:
        """Find optimal migrations based on memory per request balancing."""
        
        self.memory_history.update_memory_history(
            gpu_to_model_mapping, 
            model_queues, 
            gpu_available_memory,
            self.model_weights_info,
            self.gpu_mem
        )
        self.model_request_tracker.update_request_history(model_queues)
        
        current_memory_per_request = self._calculate_memory_per_request(
            gpu_to_model_mapping, model_queues, gpu_available_memory
        )
        
        for gpu_id, (memory_per_req, total_reqs) in current_memory_per_request.items():
            logger.info(f"GPU {gpu_id}:")
            logger.info(f"  Memory per request (smoothed requests): {memory_per_req:.2f} GB")
            logger.info(f"  Total requests (smoothed): {total_reqs:.2f}")
            logger.info(f"  Available memory: {gpu_available_memory[gpu_id]:.2f} GB")
            for model_name in gpu_to_model_mapping[gpu_id]:
                model_reqs = self.model_request_tracker.get_model_request_stats(model_name)
                model_memory = self.model_weights_info[model_name]["model_size"]
                logger.info(f"    Model {model_name}:")
                logger.info(f"      Requests (smoothed): {model_reqs:.2f}")
                logger.info(f"      Model memory: {model_memory:.2f} GB")
        
        current_unstable_pairs = self._count_unstable_pairs(current_memory_per_request)
        
        if current_unstable_pairs == 0:
            logger.info("Memory placement is already stable, no migrations needed")
            return []
        
        logger.info(f"Current unstable pairs: {current_unstable_pairs}")
        
        # Get GPU active instance counts
        gpu_to_active_instances = self._get_gpu_to_active_instances(model_instance_state_dict)
        gpu_active_instance_count = self._get_gpu_active_instance_count(gpu_to_active_instances)
        
        # Sort GPUs by memory per request (LOWEST to HIGHEST)
        sorted_gpus = sorted(
            [(gpu_id, memory, reqs) for gpu_id, (memory, reqs) in current_memory_per_request.items()],
            key=lambda x: x[1]
        )
        
        for low_idx in range(len(sorted_gpus)):
            low_gpu_id, low_memory, low_reqs = sorted_gpus[low_idx]
            
            # Skip if this GPU has only one active instance (can't move out)
            if gpu_active_instance_count[low_gpu_id] == 1:
                continue
            
            for high_idx in range(len(sorted_gpus)-1, low_idx, -1):
                high_gpu_id, high_memory, high_reqs = sorted_gpus[high_idx]
                
                # Check if memory ratio is significant 
                if high_memory / low_memory <= self.MEMORY_PER_REQUEST_RATIO_THRESHOLD:
                    continue
                
                # prioritize migrating models with fewer requests
                models_with_req_count = []
                for model_name in gpu_to_model_mapping[low_gpu_id]:
                    model_reqs = self.model_request_tracker.get_model_request_stats(model_name)
                    models_with_req_count.append((model_name, model_reqs))
                
                sorted_models = sorted(models_with_req_count, key=lambda x: x[1])
                
                for model_name, model_reqs in sorted_models:
                    if model_reqs == 0:
                        continue
                        
                    instance_idx = None
                    for instance in model_instance_state_dict.get(model_name):
                        if instance.serving and low_gpu_id in instance.gpu_ids:
                            instance_idx = instance.instance_idx
                            break
                    
                    if instance_idx is None:
                        continue
                    
                    model_memory = self.model_weights_info[model_name]["model_size"]
                    if gpu_available_memory[high_gpu_id] < model_memory:
                        continue
                    
                    simulated_mapping = {gpu_id: models.copy() for gpu_id, models in gpu_to_model_mapping.items()}
                    simulated_mapping[low_gpu_id].remove(model_name)
                    simulated_mapping[high_gpu_id].append(model_name)
                    
                    simulated_memory_per_request = self._calculate_memory_per_request(
                        simulated_mapping, model_queues, gpu_available_memory
                    )
                    
                    simulated_unstable_pairs = self._count_unstable_pairs(simulated_memory_per_request)

                    logger.info(f"Migration Placement: model {model_name} (with {model_reqs:.2f} smoothed requests) from {low_gpu_id} to {high_gpu_id}")
                    logger.info(f"  Current unstable pairs: {current_unstable_pairs}, Simulated unstable pairs: {simulated_unstable_pairs}")
                    for gpu_id, (memory, reqs) in simulated_memory_per_request.items():
                        logger.info(f"  Simulated GPU {gpu_id}, memory_per_request: {memory:.2f} GB, total_reqs: {reqs:.2f}")
                    
                    if simulated_unstable_pairs < current_unstable_pairs:
                        logger.info(f"Migration reduces unstable pairs from {current_unstable_pairs} to {simulated_unstable_pairs}")
                        return [(model_name, instance_idx, high_gpu_id)]
                    logger.info("Migration does not reduce unstable pairs, continue")
        
        logger.info("No migrations found that reduce unstable pairs")
        return []

    def _find_optimal_migrations(
        self,
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        model_queues: Dict[str, ModelQueueTracker],
        gpu_available_memory: Dict[int, float],
        model_violation_stats: Dict[str, Tuple[int, float, int]],
        gpu_to_model_mapping: Dict[int, List[str]]
    ) -> List[Tuple[str, int, int]]:
        """Find optimal migrations based on the selected policy."""
        if self.migrate_policy == "memory_per_request":
            return self._find_optimal_migrations_by_memory(
                model_instance_state_dict, model_queues, gpu_available_memory, gpu_to_model_mapping
            )
        else:  # violation policy
            return self._find_optimal_migrations_by_violation(
                model_instance_state_dict, model_queues, gpu_available_memory, 
                model_violation_stats, gpu_to_model_mapping
            )

    def _find_inactive_models_with_requests(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]]
    ) -> List[str]:
        """Find inactive models that have pending requests.
        Return a list of model names.
        """
        inactive_models_with_requests = []
        
        for model_name, queue_tracker in model_queues.items():
            if queue_tracker.get_num_waiting_reqs() > 0 or queue_tracker.get_num_running_reqs() > 0:
                has_active_instance = False
                for instance in model_instance_state_dict.get(model_name):
                    if instance.serving:
                        has_active_instance = True
                        break
                        
                if not has_active_instance:
                    inactive_models_with_requests.append(model_name)
        
        return inactive_models_with_requests
    
    def _place_inactive_model(
        self,
        model_name: str,
        instance_idx: int,
        model_memory_required: float,
        gpu_available_memory: Dict[int, float],
        sorted_clusters: List[List[int]],
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]]
    ) -> Optional[int]:
        """Place an inactive model with requests.
        Uses cluster-based approach to find suitable GPU.
        Returns the target GPU ID if placement is successful, None otherwise.
        """
        for cluster in sorted_clusters:
            gpu_time_budgets = []
            for gpu_id in cluster:
                # Check if the GPU has enough memory
                if gpu_available_memory[gpu_id] < model_memory_required:
                    continue
                
                total_budget = 0
                total_reqs = 0
                
                for m_name, queue in model_queues.items():
                    instance_states = model_instance_state_dict.get(m_name)
                    for instance in instance_states:
                        if instance.serving and gpu_id in instance.gpu_ids:
                            for req in queue.running_reqs + list(queue.waiting_reqs):
                                total_budget += req.remaining_time_budget if req.remaining_time_budget is not None else 0
                                total_reqs += 1
                
                avg_budget = total_budget / total_reqs if total_reqs > 0 else float('inf')
                gpu_time_budgets.append((gpu_id, avg_budget))
            
            sorted_gpus_by_budget = sorted(gpu_time_budgets, key=lambda x: x[1], reverse=True)
            
            for gpu_id, _ in sorted_gpus_by_budget:
                if gpu_available_memory[gpu_id] >= model_memory_required:
                    gpu_available_memory[gpu_id] -= model_memory_required
                    return gpu_id
        return None
    
    def _prepare_gpu_clusters(
        self, 
        gpu_available_memory: Dict[int, float]
    ) -> List[List[int]]:
        """Prepare GPU clusters based on available memory."""
        sorted_gpus = sorted([(gpu_id, gpu_available_memory[gpu_id]) 
                             for gpu_id in range(self.num_gpus)],
                            key=lambda x: x[1], reverse=True)
        
        gpu_clusters = []
        current_cluster = []
        
        for gpu_id, mem in sorted_gpus:
            if not current_cluster:
                current_cluster.append(gpu_id)
            else:
                max_mem_in_current_cluster = max(gpu_available_memory[gpu_id] for gpu_id in current_cluster)
                if max_mem_in_current_cluster - mem <= 5:  # 5GB threshold for clustering
                    current_cluster.append(gpu_id)
                else:
                    gpu_clusters.append(current_cluster)
                    current_cluster = [gpu_id]
        
        if current_cluster:
            gpu_clusters.append(current_cluster)
        
        cluster_avg_memory = []
        for i, cluster in enumerate(gpu_clusters):
            avg_mem = sum(gpu_available_memory[gpu_id] for gpu_id in cluster) / len(cluster)
            cluster_avg_memory.append((i, avg_mem))
        
        return [gpu_clusters[idx] for idx, _ in sorted(cluster_avg_memory, key=lambda x: x[1], reverse=True)]
    
    def _kv_reserve_gb(self, model_name: str, queue: Optional[ModelQueueTracker]) -> float:
        """A1.1: KV of PRISM_KV_RESERVE_REQS requests of the model's mean size (prompt + output of its queued
        requests; 1024 tokens if none), on top of the weights, to activate it."""
        if self.KV_RESERVE_REQS <= 0:
            return 0.0
        reqs = (list(queue.waiting_reqs) + list(queue.running_reqs)) if queue else []
        sizes = [(r.prompt_len or 0) + (r.output_len or 0) for r in reqs if r.prompt_len is not None]
        return structural.kmin_gb(self.KV_RESERVE_REQS, sizes, self.model_weights_info[model_name]["cell_size"])

    def _activation_need_gb(self, model_name: str, queue: Optional[ModelQueueTracker]) -> float:
        """Free GB (after pending activations) needed to activate a model: weights + headroom + activation KV, and
        with A1.1 the KV of b requests instead of the activation KV when larger, plus kvcached's floor."""
        return structural.activation_need_gb(
            self.model_weights_info[model_name]["model_size"], self.ACTIVATION_HEADROOM, self.ACTIVATION_KV_GB,
            self._kv_reserve_gb(model_name, queue), self.KV_FLOOR_GB)

    def _resident_long_enough(self, model_name: str, now: float) -> bool:
        """A1.3: evictable only after PRISM_MIN_RESIDENCY s resident (always, with it off)."""
        since = self.active_since.get(model_name)
        return structural.resident_long_enough(None if since is None else now - since, self.MIN_RESIDENCY)

    def _deadline_snapshot(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]],
        blocked_keys: Set[Tuple[str, int]],
        gpu_available_memory: Dict[int, float],
        now: float,
    ) -> "deadline.Snapshot":
        """The state the F6a decision functions see (policy/deadline.py)."""
        active = {inst.model_name: (gpu_id, inst) for gpu_id, insts in gpu_to_active_instances.items() for inst in insts}
        ahead = len(self.pending_activations)
        models = {}
        for name in model_instance_state_dict:
            queue = model_queues.get(name)
            weights = self.model_weights_info[name]["model_size"]
            waiting = []
            for r in (queue.waiting_reqs if queue else []):
                if r.arrival_time is None or r.is_warmup:
                    continue
                pre = r.preempted_time if r.state == ReqState.PREEMTED else None
                waiting.append(deadline.ReqSnap(arrival=r.arrival_time, slo=r.slo, prompt_len=r.prompt_len or 0,
                                                preempted_at=pre))
            running = queue.get_num_running_reqs() if queue else 0
            gpu, inst = active.get(name, (None, None))
            run_tokens = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.running_reqs) if queue else 0
            models[name] = deadline.ModelSnap(
                name=name, gpu=gpu,
                need_gb=self._activation_need_gb(name, queue),
                free_gb=self._model_memory(name, run_tokens),
                waiting=waiting, running=running,
                active_since=self.active_since.get(name) if gpu is not None else None,
                c_at=activation_cost(weights, ahead, self.CAT_COEF),
                c_rot=rotation_cost(weights, self.CROT_TABLE) if self.CROT_TABLE else 0.0,
                c_rot_p=rotation_cost(weights, self.CROT_P) if self.CROT_P else 0.0,
                c_rot_np=rotation_cost(weights, self.CROT_NP) if self.CROT_NP else 0.0,
                rate=self._arrival_rate(queue, now) if self.LVF_PREDICTIVE else 0.0,
                slo_typ=self._typical_slo(queue) if self.LVF_PREDICTIVE else None,
                # in flight = victims evicted for it and its activation not sent yet (ACTIVATING counts as active
                # here, so the rotation cap does not wait for the load; same as before D45)
                reserved=gpu is None and self._reserved(name, now),
                cooldown=self.pressure_cooldown_until.get(name, 0) > now
                or (self.SWAP_RESERVATION_END == "event" and gpu is None and self._reserved(name, now)),
                blocked=inst is not None and (name, inst.instance_idx) in blocked_keys,
            )
        in_flight = sum(1 for m in models.values() if m.reserved)
        return deadline.Snapshot(now=now, models=models, gpu_free=dict(gpu_available_memory),
                                 prefill_a=self.PREFILL_A, prefill_b=self.PREFILL_B, in_flight=in_flight)

    def _deadline_actions(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]],
        blocked_keys: Set[Tuple[str, int]],
        gpu_available_memory: Dict[int, float],
    ):
        """PRISM_EVICTION=edf|lvf: (activation_plan {(model, gpu): gpu}, evictions [(instance, gpu, reason)])."""
        now = time.time()
        snap = self._deadline_snapshot(model_queues, model_instance_state_dict, gpu_to_active_instances,
                                       blocked_keys, gpu_available_memory, now)
        if self.EVICTION == "edf":
            params = deadline.Params(floor=self.EDF_FLOOR, budget=self.EDF_BUDGET, min_residency=self.MIN_RESIDENCY)
            dec = deadline.edf_select(snap, params)
        elif self.EVICTION == "loss":
            params = deadline.Params(budget=self.EDF_BUDGET, min_residency=self.MIN_RESIDENCY, theta=self.LOSS_THETA)
            dec = deadline.loss_select(snap, params)
        else:
            params = deadline.Params(alpha=self.LVF_ALPHA, beta_f=self.LVF_BETA_F, beta_b=self.LVF_BETA_B,
                                     budget=self.LVF_BUDGET, min_residency=self.MIN_RESIDENCY,
                                     cost_aware=self.LVF_COST_AWARE, margin=self.LVF_MARGIN,
                                     preempt=self.SWAP_PREEMPT, preempt_per_swap=self.LVF_PREEMPT == "per_swap",
                                     preempt_lambda=self.LVF_PREEMPT_LAMBDA, predictive=self.LVF_PREDICTIVE)
            dec = deadline.lvf_select(snap, params)
        self.dlog.policy(self.EVICTION, dec.scores, in_flight=snap.in_flight, rotated_for=dec.rotated_for)
        for name in dec.rotated_for:
            self.pressure_cooldown_until[name] = now + self.PRESSURE_COOLDOWN
            self._reserve(name, now)
        for name in dec.unplaced:
            logger.warning(f"No suitable GPU found for inactive model {name}")
            self.dlog.note("no_fit", name, need_gb=snap.models[name].need_gb)
        activation_plan = {(name, gpu): gpu for name, gpu in dec.activations}
        by_name = {inst.model_name: inst for insts in gpu_to_active_instances.values() for inst in insts}
        evictions = [(by_name[name], gpu, reason, dec.preempt.get(name)) for name, gpu, reason in dec.victims]
        for name, score in dec.scores.items():
            logger.info(f"{self.EVICTION} score {name}: {score}")
        return activation_plan, evictions

    def _log_lapsed_reservations(self, now: float, active_models: Set[str]):
        """F5.0f (D30): a model that victims were evicted for keeps priority on the freed memory until its reservation
        runs out (SWAP_RESERVATION s in timer mode; in event mode, D45, only the SWAP_RESERVATION_MAX_S safety bound,
        since _end_reservations ends it earlier on activation). When it runs out with the model neither active nor
        being activated, log it once, with the models activated since the reservation was made (who took the
        memory). Only logs: the reservations themselves are untouched."""
        pending = {m for (m, _) in self.pending_activations}
        for name, until in self.swap_reservation_until.items():
            if until > now or (name, until) in self._reservation_logged:
                continue
            self._reservation_logged.add((name, until))
            if name in active_models or name in pending:
                continue  # the reservation was used
            start = self.swap_reservation_start.get(name, until - self.SWAP_RESERVATION)
            took = sorted(m for m in active_models if self.active_since.get(m, -1.0) >= start)
            took += sorted(m for m in pending if m != name)
            self.dlog.note("reservation_lapsed", name, reserved_s=until - start, lapsed_ago_s=now - until,
                           taken_by=took)
            logger.info(f"Reservation of {name} lapsed {now - until:.1f} s ago without activation; "
                        f"activated meanwhile: {took}")

    def _deadlock_check(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
        gpu_to_active_instances: Dict[int, List[ModelInstanceState]],
        taken: Set[Tuple[str, int]],
        acting: bool,
    ) -> Optional[Tuple[ModelInstanceState, int, str]]:
        """A1.2: advance the stall clock and, after PRISM_DEADLOCK_S s stalled, return the victim (instance, gpu,
        reason). `acting`: this cycle already deactivates or activates a model, which is a transition."""
        now = time.time()
        served = float(sum(q.served_tokens for q in model_queues.values()))
        active = {inst.model_name: (gpu_id, inst) for gpu_id, insts in gpu_to_active_instances.items() for inst in insts}
        with_waiting = [m for m in active
                        if any(not r.is_warmup for r in model_queues[m].waiting_reqs)]
        # loads in progress (D45). DEACTIVATING is left out on purpose: a victim finishing its batch serves tokens,
        # and counting it would change the detector (decided to keep the pre-D45 behaviour)
        moving = sum(1 for insts in model_instance_state_dict.values() for i in insts
                     if i.state == ModelState.ACTIVATING)
        transitions = len(self.pending_activations) + moving + (1 if acting else 0)
        stalled = self.deadlock.update(structural.StallInput(now=now, served_total=served,
                                                             active_with_waiting=len(with_waiting),
                                                             transitions=transitions))
        if not self.deadlock.fired(stalled):
            return None
        cands = []
        for name, (gpu_id, inst) in active.items():
            density, _, _ = self._keep_value(name, model_queues[name])
            since = self.active_since.get(name)
            cands.append(structural.VictimCand(name=name, gpu=gpu_id, value_per_gb=density,
                                               active_for_s=None if since is None else now - since,
                                               excluded=(name, inst.instance_idx) in taken))
        pick = structural.deadlock_victim(cands, self.MIN_RESIDENCY)
        # the model it unblocks: the active one with the oldest waiting request
        oldest = min(with_waiting, key=lambda m: model_queues[m].get_earliest_arrival_time())
        state = {c.name: {"value_per_gb": round(c.value_per_gb, 3), "active_for_s": c.active_for_s,
                          "waiting": model_queues[c.name].get_num_waiting_reqs(),
                          "running": model_queues[c.name].get_num_running_reqs(), "excluded": c.excluded}
                 for c in cands}
        self.dlog.note("deadlock", pick.name if pick else None, stalled_s=stalled, served_tokens=served,
                       unblocks=oldest, candidates=state)
        logger.warning(f"Impasse detector (A1.2): no token for {stalled:.1f} s with {len(with_waiting)} active "
                       f"models waiting; victim {pick.name if pick else None}; candidates {state}")
        if pick is None:
            return None
        self.deadlock.reset(now)
        return active[pick.name][1], pick.gpu, f"deadlock break for {oldest}"

    def gen_actions(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
    ) -> List[BaseAction]:

        start_total = time.time()
        self.dlog.begin(start_total)
        model_instance_to_action_dict: Dict[Tuple[str, int], List[BaseAction]] = {}

        # Pre-compute commonly used data structures to avoid redundant calculation
        start_precompute = time.time()
        self._update_req_remaining_time_budget(model_queues)
        model_violation_stats = self._calculate_model_violation_stats(model_queues)
        gpu_to_model_mapping = self._get_gpu_to_model_mapping(model_instance_state_dict)
        gpu_to_active_instances = self._get_gpu_to_active_instances(model_instance_state_dict)
        active_models = {inst.model_name for insts in gpu_to_active_instances.values() for inst in insts}
        for model_name in list(self.active_since):
            if model_name not in active_models:
                del self.active_since[model_name]
        # Residency (A1.3, PRISM_SWAP_MIN_RESIDENCY, fair) counts from when the weights are loaded (D45): while
        # ACTIVATING it restarts every cycle, then it is the time the GPU scheduler reported the load.
        now = time.time()
        for insts in gpu_to_active_instances.values():
            for inst in insts:
                name = inst.model_name
                if inst.state == ModelState.ACTIVATING:
                    self.active_since[name] = now
                elif name in self.active_since and inst.state_since > self.active_since[name]:
                    self.active_since[name] = inst.state_since  # loaded since the last cycle
                else:
                    self.active_since.setdefault(name, now)
        if self.EVICTION in ("throughput", "value") or self.deadlock.enabled:
            self._update_tput(model_queues, active_models)
        if self.dlog.enabled:
            self.dlog.models(time.time(), model_queues, model_instance_state_dict, self.model_weights_info,
                             self.active_since)
        self._end_reservations(time.time(), active_models, model_queues)
        self._log_lapsed_reservations(time.time(), active_models)
        end_precompute = time.time()
        logger.info(f"Time for preprocessing data structures: {end_precompute - start_precompute:.4f}s")

        for model_name, model_instances in model_instance_state_dict.items():
            logger.info(f"Model {model_name}:")
            for model_instance in model_instances:
                logger.info(f"  {model_instance}")

        # 1. Handle idle instance eviction
        start_idle_check = time.time()
        idle_instance_keys = set()
        idle_instances = self._check_idle_instance_eviction(
            model_queues, gpu_to_active_instances
        )

        for gpu_id, evictable_instances in idle_instances.items():
            for model_instance in evictable_instances:
                instance_key = (model_instance.model_name, model_instance.instance_idx)
                idle_instance_keys.add(instance_key)
                model_instance_to_action_dict.setdefault(
                    instance_key, []
                ).append(
                    DeactivateAction(
                        model_name=model_instance.model_name,
                        instance_idx=model_instance.instance_idx,
                        preempt=False,
                        preempt_mode="RECOMPUTE",
                        evict_waiting_requests=True,
                        gpu_id=gpu_id,
                    )
                )
                logger.info(f"ACTION: deactivate {model_instance.model_name}:{model_instance.instance_idx} on GPU {gpu_id}. Reason: idle instance eviction")
                self.dlog.action("deactivate", model_instance.model_name, gpu_id, "idle instance eviction", preempt=False)
        end_idle_check = time.time()
        logger.info(f"Time for idle instance eviction: {end_idle_check - start_idle_check:.4f}s")

        start_mem_check = time.time()
        gpu_available_memory = {}
        pending_gb = self._pending_activation_gb()
        for gpu_id in range(self.num_gpus):
            free_gb = get_available_gpu_memory("cuda", gpu_id)
            gpu_available_memory[gpu_id] = free_gb - pending_gb.get(gpu_id, 0.0)
            self.dlog.gpu(gpu_id, free_gb, pending_gb.get(gpu_id, 0.0), gpu_available_memory[gpu_id],
                          [m for (m, g) in self.pending_activations if g == gpu_id])
            logger.info(f"GPU {gpu_id}, mem {gpu_available_memory[gpu_id]}")
            if pending_gb.get(gpu_id):
                logger.info(f"GPU {gpu_id}: {pending_gb[gpu_id]:.1f} GB promised to pending activations "
                            f"{[m for (m, g) in self.pending_activations if g == gpu_id]}")
        end_mem_check = time.time()
        logger.info(f"Time for checking GPU memory: {end_mem_check - start_mem_check:.4f}s")
        
        # 2. Migrate active models - using optimized approach
        start_migrations = time.time()
        migrations = self._find_optimal_migrations(
            model_instance_state_dict, 
            model_queues,
            gpu_available_memory,
            model_violation_stats,
            gpu_to_model_mapping
        )

        valid_migrations = []
        for model_name, source_gpu_id, target_gpu_id in migrations:
            instances = gpu_to_active_instances[target_gpu_id]

            if len(instances) < self.workers_per_gpu:
                valid_migrations.append((model_name, source_gpu_id, target_gpu_id))
            else:
                logger.info(f"Skipping migration {model_name} from {source_gpu_id} to {target_gpu_id} because target GPU {target_gpu_id} has {len(instances)} active instances")

        migrations = valid_migrations
        for model_name, source_gpu_id, target_gpu_id in migrations:
            model_memory_required = self.model_weights_info[model_name]["model_size"]
            gpu_available_memory[target_gpu_id] -= model_memory_required
            logger.info(f"PLANNING: migrate model {model_name} from GPU {source_gpu_id} to GPU {target_gpu_id}")

        end_migrations = time.time()
        logger.info(f"Time for finding migrations: {end_migrations - start_migrations:.4f}s")
        
        # 3. Activate inactive models with requests
        start_inactive = time.time()
        if self.EVICTION in ("edf", "lvf", "loss"):
            activation_plan, evictions = self._deadline_actions(
                model_queues, model_instance_state_dict, gpu_to_active_instances, idle_instance_keys,
                gpu_available_memory)
            inactive_models_with_requests = []
        else:
            inactive_models_with_requests = self._find_inactive_models_with_requests(model_queues, model_instance_state_dict)
        
        sorted_inactive_models = sorted(
            inactive_models_with_requests,
            key=lambda model_name: model_violation_stats[model_name][1],
            reverse=True
        )
        # A model that victims were evicted for (throughput swap) gets the freed memory first.
        now = time.time()
        sorted_inactive_models.sort(key=lambda m: 0 if self._reserved(m, now) else 1)

        sorted_clusters = self._prepare_gpu_clusters(gpu_available_memory)
        
        if self.EVICTION not in ("edf", "lvf", "loss"):
            activation_plan = {}
        unplaced_models = []
        for model_name in sorted_inactive_models:
            model_memory_required = self._activation_need_gb(model_name, model_queues.get(model_name))
            target_gpu = self._place_inactive_model(
                model_name, 0, model_memory_required,  # instance_idx doesn't matter here
                gpu_available_memory, sorted_clusters, model_queues, model_instance_state_dict
            )
            
            if target_gpu is not None:
                activation_plan[(model_name, target_gpu)] = target_gpu
            else:
                logger.warning(f"No suitable GPU found for inactive model {model_name}")
                self.dlog.note("no_fit", model_name, need_gb=model_memory_required)
                unplaced_models.append(model_name)

        # 3b. Alternative eviction strategies (PRISM_EVICTION): free room for the models that did not fit
        preempt = False
        if self.EVICTION in ("throughput", "value"):
            swap_for = unplaced_models
            if self.EVICTION == "value":  # A10.1: only models with a request that can still meet its deadline
                swap_for = [m for m in unplaced_models if self._has_viable(m, model_queues.get(m), time.time())]
            evictions = self._throughput_swaps(
                swap_for, model_queues, gpu_to_active_instances, idle_instance_keys, gpu_available_memory
            )
            preempt = self.SWAP_PREEMPT
        elif self.EVICTION in ("edf", "lvf", "loss"):
            preempt = self.SWAP_PREEMPT
        elif self.EVICTION != "idle":
            evictions = self._pressure_evictions(
                unplaced_models, model_queues, gpu_to_active_instances, idle_instance_keys
            )
        else:
            evictions = []
        for victim, gpu_id, reason, *own in evictions:
            pre = own[0] if own and own[0] is not None else preempt  # A9.4: per-victim choice
            instance_key = (victim.model_name, victim.instance_idx)
            idle_instance_keys.add(instance_key)
            model_instance_to_action_dict.setdefault(instance_key, []).append(
                DeactivateAction(
                    model_name=victim.model_name,
                    instance_idx=victim.instance_idx,
                    preempt=pre,
                    preempt_mode="RECOMPUTE",
                    evict_waiting_requests=True,
                    gpu_id=gpu_id,
                )
            )
            logger.info(f"ACTION: deactivate {victim.model_name}:{victim.instance_idx} on GPU {gpu_id}. Reason: {reason}")
            self.dlog.action("deactivate", victim.model_name, gpu_id, reason, preempt=pre)

        # 3c. A1.2 impasse detector (PRISM_DEADLOCK_S): after any strategy's own decisions
        if self.deadlock.enabled:
            victim = self._deadlock_check(model_queues, model_instance_state_dict, gpu_to_active_instances,
                                          idle_instance_keys, bool(evictions) or bool(activation_plan))
            if victim is not None:
                inst, gpu_id, reason = victim
                instance_key = (inst.model_name, inst.instance_idx)
                idle_instance_keys.add(instance_key)
                model_instance_to_action_dict.setdefault(instance_key, []).append(
                    DeactivateAction(model_name=inst.model_name, instance_idx=inst.instance_idx, preempt=True,
                                     preempt_mode="RECOMPUTE", evict_waiting_requests=True, gpu_id=gpu_id))
                logger.info(f"ACTION: deactivate {inst.model_name}:{inst.instance_idx} on GPU {gpu_id}. Reason: {reason}")
                self.dlog.action("deactivate", inst.model_name, gpu_id, reason, preempt=True)

        end_inactive = time.time()

        for model_name, gpu_id in activation_plan.keys():
            logger.info(f"PLANNING: activate inactive model {model_name} on GPU {gpu_id}. Reason: inactive models but with requests")

        logger.info(f"Time for planning inactive model activation: {end_inactive - start_inactive:.4f}s")
        
        # 4. Apply migrations from step 2
        start_apply_actions = time.time()
        for model_name, source_gpu_id, target_gpu_id in migrations:
            # Deactivate the instance on source GPU
            source_instance_key = (model_name, source_gpu_id)
            if source_instance_key not in idle_instance_keys:
                model_instance_to_action_dict.setdefault(source_instance_key, []).append(
                    DeactivateAction(
                        model_name=model_name,
                        instance_idx=source_gpu_id,
                        preempt=False,
                        preempt_mode="RECOMPUTE",
                        evict_waiting_requests=True,
                        gpu_id=source_gpu_id,
                    )
                )
                
                # Activate the instance on target GPU
                target_instance_key = (model_name, target_gpu_id)
                model_instance_to_action_dict.setdefault(target_instance_key, []).append(
                    ActivateAction(
                        model_name=model_name,
                        instance_idx=target_gpu_id,
                        memory_pool_size=self.MEMORY_POOL_BUDGET,
                        gpu_id=target_gpu_id,
                    )
                )
                self._add_pending_activation(model_name, target_gpu_id)
                logger.info(f"ACTION: deactivate {model_name} on GPU {source_gpu_id} and activate {model_name} on GPU {target_gpu_id}. Reason: migrate model")
                self.dlog.action("migrate", model_name, target_gpu_id, "migrate model", source_gpu=source_gpu_id)

        # 5. Activate inactive models
        for (model_name, instance_idx), gpu_id in activation_plan.items():
            instance_key = (model_name, instance_idx)
            model_instance_to_action_dict.setdefault(instance_key, []).append(
                ActivateAction(
                    model_name=model_name,
                    instance_idx=instance_idx,
                    memory_pool_size=self.MEMORY_POOL_BUDGET,
                    gpu_id=gpu_id,
                )
            )
            self._add_pending_activation(model_name, gpu_id)
            logger.info(f"ACTION: activate inactive model {model_name} on GPU {gpu_id}. Reason: inactive models but with requests")
            self.dlog.action("activate", model_name, gpu_id, "inactive models but with requests")
        end_apply_actions = time.time()
        logger.info(f"Time for creating action list: {end_apply_actions - start_apply_actions:.4f}s")
        
        end_total = time.time()
        logger.info(f"Total time for global scheduling: {end_total - start_total:.4f}s")

        all_actions = []

        for actions in model_instance_to_action_dict.values():
            sorted_actions = sorted(actions, key=lambda action: 0 if isinstance(action, DeactivateAction) else 1)
            all_actions.extend(sorted_actions)
        self.dlog.end()

        return all_actions