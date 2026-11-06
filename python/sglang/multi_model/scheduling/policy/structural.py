"""F4: structural constraints A1 (PLANO_AGENTE.md section A1), independent of the policy that picks models.

Pure decision functions; SimpleGlobalPolicy builds their inputs and applies the result. Every constraint is off by
default (Prism as published):

A1.1 KV reserve at activation (PRISM_KV_RESERVE_REQS = b > 0)
     Activate m only if  free − pending activations ≥ W_m + headroom + max(KV at activation, K_min(m)) + floor,
     K_min(m) = b requests of the model's mean size (prompt + output) × KV bytes per token, and floor = the part of
     the GPU kvcached never maps for KV (kvcached/slab_allocator.py: GPU_UTILIZATION = 0.95, so 5% of the GPU;
     PRISM_KV_FLOOR_FRAC). Without the floor the controller fills the GPU with weights down to ~1 GB free, below
     the 7.2 GB kvcached keeps out of the KV pool, and no model gets a KV page: the T1 impasse (reports/erros.md).
A1.2 Impasse detector (PRISM_DEADLOCK_S = Δ_imp > 0)
     If for Δ_imp seconds no active model served a token (prefill or decode, the engines' per-second counts) while
     an active model has waiting requests and no activation or deactivation is in flight, evict the active model
     of least value: A0.3's criterion (tokens/s served over 30 s plus its own queued tokens over 30 s, per GB it
     occupies), preempting its running requests (they cannot progress anyway).
A1.3 Minimum residency (PRISM_MIN_RESIDENCY = T_min > 0)
     No eviction (idle, pressure, fair, throughput, deadline policies, A1.2) of a model resident for less than T_min.
"""
import dataclasses
from typing import List, Optional, Sequence


def activation_need_gb(weights_gb: float, headroom_gb: float, activation_kv_gb: float, kmin_gb: float,
                       floor_gb: float) -> float:
    """GB that must be free (after pending activations) to activate a model. With A1.1 off (kmin = floor = 0) this
    is Prism's rule with R2.1: weights + headroom + activation KV."""
    return weights_gb + headroom_gb + max(activation_kv_gb, kmin_gb) + floor_gb


def kmin_gb(b: float, sizes_tokens: Sequence[float], cell_bytes: float, default_tokens: float = 1024.0) -> float:
    """K_min(m): KV of b requests of the model's mean size (its queued + running requests; default_tokens if none)."""
    if b <= 0:
        return 0.0
    mean = sum(sizes_tokens) / len(sizes_tokens) if sizes_tokens else default_tokens
    return b * mean * cell_bytes / (1 << 30)


def resident_long_enough(active_for_s: Optional[float], min_residency_s: float) -> bool:
    """A1.3: an active model may be evicted only after T_min s resident (unknown residency counts as long enough,
    the state before the controller saw the model active)."""
    return min_residency_s <= 0 or active_for_s is None or active_for_s >= min_residency_s


@dataclasses.dataclass
class StallInput:
    """What the detector sees in one controller cycle."""
    now: float
    served_total: float           # sum of every model's served_tokens (monotone; tokens only come from engines)
    active_with_waiting: int      # active models with waiting (non-warmup) requests
    transitions: int              # activations pending + models ACTIVATING / DEACTIVATING


class DeadlockDetector:
    """A1.2 stall clock. The clock runs while the system could make progress (an active model has work) and none
    does (no token), with no transition in flight that will change memory; anything else resets it."""

    def __init__(self, delta_s: float):
        self.delta_s = delta_s
        self.since: Optional[float] = None
        self.last_served: Optional[float] = None

    @property
    def enabled(self) -> bool:
        return self.delta_s > 0

    def update(self, x: StallInput) -> float:
        """Seconds stalled so far (0 when not stalled)."""
        progressed = self.last_served is not None and x.served_total != self.last_served
        self.last_served = x.served_total
        if x.active_with_waiting == 0 or x.transitions > 0:
            self.since = None
            return 0.0
        if progressed or self.since is None:  # the stall counts from the last cycle that saw progress
            self.since = x.now
            return 0.0
        return x.now - self.since

    def fired(self, stalled_s: float) -> bool:
        return self.enabled and stalled_s >= self.delta_s

    def reset(self, now: float):
        """After an eviction: the next one only after another Δ_imp of stall."""
        self.since = None


@dataclasses.dataclass
class VictimCand:
    name: str
    gpu: int
    value_per_gb: float           # A0.3: (served tokens/s + queued tokens / 30 s) / GB occupied
    active_for_s: Optional[float]
    excluded: bool = False        # already leaving this cycle (idle eviction) or otherwise unavailable


def deadlock_victim(cands: List[VictimCand], min_residency_s: float) -> Optional[VictimCand]:
    """A1.2: the active model of least value per GB among those resident for at least T_min (A1.3). Ties: the one
    active for longest (it has had its turn)."""
    ok = [c for c in cands if not c.excluded and resident_long_enough(c.active_for_s, min_residency_s)]
    if not ok:
        return None
    return min(ok, key=lambda c: (c.value_per_gb, -(c.active_for_s or 0.0), c.name))
