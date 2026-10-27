import logging
import os
import time
from itertools import chain
from typing import Dict, List, Set, Tuple, Optional, DefaultDict
from collections import defaultdict, deque

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
        model_tp: Optional[Dict[str, int]] = None,
    ):
        self.num_gpus = num_gpus
        # Tensor parallelism (vLLM worker pool): a TP model's instance spans a GPU group and holds 1/tp
        # of its weights on each GPU; it is scheduled at the group's first GPU (Prism, Appendix A.2.2).
        self.model_tp = model_tp or {}
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
        #             their tokens/s by PRISM_SWAP_MARGIN. Victims are preempted (PRISM_SWAP_PREEMPT=1: running
        #             requests recomputed later) and/or drained first (PRISM_SWAP_DRAIN=1: serve their accepted
        #             requests for up to PRISM_SWAP_DRAIN_TIMEOUT s).
        self.EVICTION = os.environ.get("PRISM_EVICTION", "idle")
        assert self.EVICTION in ["idle", "pressure", "adaptive", "fair", "throughput"]
        self.SWAP_MARGIN = float(os.environ.get("PRISM_SWAP_MARGIN", 0.2))
        self.SWAP_MIN_RESIDENCY = float(os.environ.get("PRISM_SWAP_MIN_RESIDENCY", 20))
        self.SWAP_AGING_S = float(os.environ.get("PRISM_SWAP_AGING_S", 30))
        self.SWAP_PREEMPT = os.environ.get("PRISM_SWAP_PREEMPT", "0") == "1"
        self.SWAP_DRAIN = os.environ.get("PRISM_SWAP_DRAIN", "0") == "1"
        self.SWAP_DRAIN_TIMEOUT = float(os.environ.get("PRISM_SWAP_DRAIN_TIMEOUT", 15))
        self.SWAP_RESERVATION = 15.0  # s the swapped-in model keeps priority for the freed memory
        self.DEMAND_WINDOW = 30.0  # s over which a waiting model's queued tokens count as its demand
        self.served_history: DefaultDict[str, deque] = defaultdict(deque)  # (time, served_tokens) per model
        self.served_tput: Dict[str, float] = {}  # tokens/s each active model served over DEMAND_WINDOW
        self.swap_reservation_until: Dict[str, float] = {}
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
                if instance.state == ModelState.ACTIVE:
                    # A TP instance is scheduled at its first GPU.
                    for gpu_id in instance.gpu_ids[:1]:
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
                if model_instance.model_name in idle_models:
                    evictable_instances[gpu_id].append(model_instance)
        
        return evictable_instances

    def _add_pending_activation(self, model_name: str, gpu_id: int):
        if self.ACTIVATION_ACCOUNTING:
            gb = self.model_weights_info[model_name]["model_size"] / self.model_tp.get(model_name, 1)
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
            if (inst.model_name, inst.instance_idx) not in taken and self.model_tp.get(inst.model_name, 1) == 1
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
                if (name, inst.instance_idx) in taken or self.model_tp.get(name, 1) != 1:
                    continue
                if now - self.active_since.get(name, now) < self.SWAP_MIN_RESIDENCY:
                    continue
                queue = model_queues[name]
                tokens = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.running_reqs)
                mem = self._model_memory(name, tokens)
                # what keeping it is worth: tokens/s it served plus its own queued work over the window
                backlog = sum((r.prompt_len or 0) + (r.output_len or 0) for r in queue.waiting_reqs)
                tput = self.served_tput.get(name, 0.0) + backlog / self.DEMAND_WINDOW
                candidates[gpu_id].append((tput / mem, tput, mem, inst))
        for cands in candidates.values():
            cands.sort(key=lambda c: c[0])

        victims = []
        demand = {m: self._aged_demand(model_queues[m], now) for m in unplaced_models}
        for model_name in sorted(unplaced_models, key=lambda m: -demand[m]):
            if self.pressure_cooldown_until.get(model_name, 0) > now:
                continue
            need = self.model_weights_info[model_name]["model_size"] + self.ACTIVATION_HEADROOM + self.ACTIVATION_KV_GB
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
            self.swap_reservation_until[model_name] = now + self.SWAP_RESERVATION
        return victims

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
                if instance.state == ModelState.ACTIVE:
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
                        if instance.state == ModelState.ACTIVE and high_gpu_id in instance.gpu_ids:
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
                        if instance.state == ModelState.ACTIVE and low_gpu_id in instance.gpu_ids:
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
                    if instance.state == ModelState.ACTIVE:
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
                        if instance.state == ModelState.ACTIVE and gpu_id in instance.gpu_ids:
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
    
    def _place_inactive_tp_model(
        self,
        model_name: str,
        memory_per_rank: float,
        gpu_available_memory: Dict[int, float],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
    ) -> Optional[int]:
        """Place an inactive TP model on one of its GPU groups: one TP part per GPU (anti-affinity), on
        the group whose most loaded GPU has the most free memory, if every GPU fits a part. Returns the
        group's first GPU (the instance index) or None."""
        candidates = []
        for instance in model_instance_state_dict.get(model_name, []):
            group = instance.gpu_ids
            if all(gpu_available_memory[g] >= memory_per_rank for g in group):
                candidates.append((min(gpu_available_memory[g] for g in group), group))
        if not candidates:
            return None
        _, group = max(candidates, key=lambda c: c[0])
        for g in group:
            gpu_available_memory[g] -= memory_per_rank
        return group[0]

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
    
    def gen_actions(
        self,
        model_queues: Dict[str, ModelQueueTracker],
        model_instance_state_dict: Dict[str, List[ModelInstanceState]],
    ) -> List[BaseAction]:

        start_total = time.time()
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
        for model_name in active_models:
            self.active_since.setdefault(model_name, time.time())
        if self.EVICTION == "throughput":
            self._update_tput(model_queues, active_models)
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
        end_idle_check = time.time()
        logger.info(f"Time for idle instance eviction: {end_idle_check - start_idle_check:.4f}s")

        start_mem_check = time.time()
        gpu_available_memory = {}
        pending_gb = self._pending_activation_gb()
        for gpu_id in range(self.num_gpus):
            gpu_available_memory[gpu_id] = get_available_gpu_memory("cuda", gpu_id) - pending_gb.get(gpu_id, 0.0)
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

        # TP models are not migrated (their instances are bound to GPU groups); they are only evicted and
        # re-activated on a group.
        migrations = [m for m in valid_migrations if self.model_tp.get(m[0], 1) == 1]
        for model_name, source_gpu_id, target_gpu_id in migrations:
            model_memory_required = self.model_weights_info[model_name]["model_size"]
            gpu_available_memory[target_gpu_id] -= model_memory_required
            logger.info(f"PLANNING: migrate model {model_name} from GPU {source_gpu_id} to GPU {target_gpu_id}")

        end_migrations = time.time()
        logger.info(f"Time for finding migrations: {end_migrations - start_migrations:.4f}s")
        
        # 3. Activate inactive models with requests
        start_inactive = time.time()
        inactive_models_with_requests = self._find_inactive_models_with_requests(model_queues, model_instance_state_dict)
        
        sorted_inactive_models = sorted(
            inactive_models_with_requests,
            key=lambda model_name: model_violation_stats[model_name][1],
            reverse=True
        )
        # A model that victims were evicted for (throughput swap) gets the freed memory first.
        now = time.time()
        sorted_inactive_models.sort(key=lambda m: 0 if self.swap_reservation_until.get(m, 0) > now else 1)

        sorted_clusters = self._prepare_gpu_clusters(gpu_available_memory)
        
        activation_plan = {}
        unplaced_models = []
        for model_name in sorted_inactive_models:
            tp = self.model_tp.get(model_name, 1)
            model_memory_required = (
                self.model_weights_info[model_name]["model_size"] / tp + self.ACTIVATION_HEADROOM + self.ACTIVATION_KV_GB
            )
            if tp > 1:
                target_gpu = self._place_inactive_tp_model(
                    model_name, model_memory_required, gpu_available_memory, model_instance_state_dict
                )
            else:
                target_gpu = self._place_inactive_model(
                    model_name, 0, model_memory_required,  # instance_idx doesn't matter here
                    gpu_available_memory, sorted_clusters, model_queues, model_instance_state_dict
                )
            
            if target_gpu is not None:
                activation_plan[(model_name, target_gpu)] = target_gpu
            else:
                logger.warning(f"No suitable GPU found for inactive model {model_name}")
                unplaced_models.append(model_name)

        # 3b. Alternative eviction strategies (PRISM_EVICTION): free room for the models that did not fit
        preempt, drain_timeout = False, None
        if self.EVICTION == "throughput":
            evictions = self._throughput_swaps(
                unplaced_models, model_queues, gpu_to_active_instances, idle_instance_keys, gpu_available_memory
            )
            preempt = self.SWAP_PREEMPT
            drain_timeout = self.SWAP_DRAIN_TIMEOUT if self.SWAP_DRAIN else None
        elif self.EVICTION != "idle":
            evictions = self._pressure_evictions(
                unplaced_models, model_queues, gpu_to_active_instances, idle_instance_keys
            )
        else:
            evictions = []
        for victim, gpu_id, reason in evictions:
            instance_key = (victim.model_name, victim.instance_idx)
            idle_instance_keys.add(instance_key)
            model_instance_to_action_dict.setdefault(instance_key, []).append(
                DeactivateAction(
                    model_name=victim.model_name,
                    instance_idx=victim.instance_idx,
                    preempt=preempt,
                    preempt_mode="RECOMPUTE",
                    evict_waiting_requests=True,
                    gpu_id=gpu_id,
                    drain_timeout=drain_timeout,
                )
            )
            logger.info(f"ACTION: deactivate {victim.model_name}:{victim.instance_idx} on GPU {gpu_id}. Reason: {reason}")

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
        end_apply_actions = time.time()
        logger.info(f"Time for creating action list: {end_apply_actions - start_apply_actions:.4f}s")
        
        end_total = time.time()
        logger.info(f"Total time for global scheduling: {end_total - start_total:.4f}s")

        all_actions = []

        for actions in model_instance_to_action_dict.values():
            sorted_actions = sorted(actions, key=lambda action: 0 if isinstance(action, DeactivateAction) else 1)
            all_actions.extend(sorted_actions)

        return all_actions