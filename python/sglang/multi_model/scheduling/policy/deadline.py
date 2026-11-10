"""Deadline-aware residency decisions (F6a, PLANO_AGENTE.md sections 4 A2.1 / A9.1, decision D24): pure functions.

Each function takes a snapshot of the controller's state (built by SimpleGlobalPolicy._deadline_snapshot) and returns
a Decision: which inactive models to activate in free memory, which active models to evict to make room (victims),
and the per-model score the decision used (logged by the decision log, F6a.4). No I/O, no clock: everything comes in
the snapshot, so tests/policy/ checks the decisions on hand-built states (section 0.6).

  edf_select  A2.1 "slack first": EDF between models. The slack of a waiting request r of model m is
              s_r = a_r + SLO_r − now − ê_r, with ê_r = Ĉ_at(m) (if m is inactive) + prefill of m's requests ahead of
              r + r's own prefill. The urgency of m is u_m = min s_r over its viable requests (s_r ≥ floor); requests
              below the floor are already lost and do not count, so lost queues are not favoured (section 4.0).
              Inactive models enter in order: models victims were evicted for (reserved), then viable ones by
              increasing u_m, then the ones with only lost requests, oldest request first. Rotation (evicting active models) only for a viable model, at most `budget`
              rotations in flight; victims (resident for ≥ min_residency) in decreasing urgency: first models with no
              viable waiting request (+inf), then the latest deadlines; a victim with viable requests is only taken if
              its urgency is later than the incoming model's. A model with only lost requests may still take the
              place of a victim with no request at all (waiting or running).
  lvf_select  A9.1 "lag first": SuperInfer's Largest Virtual-lag First between models. Waiting model:
              VLT_m = max over its waiting requests of ReLU(now − a_r − β_F·SLO_r), and for requests preempted back to
              the queue (rotated out) α·ReLU(now − t_preempt − β_B·SLO_TPOT); active model: VLT_m = −(now − active
              since). If every waiting model fits in free memory, all are activated (contention check, no rotation).
              Otherwise, in decreasing VLT, models are placed in free memory; the ones that do not fit and have
              VLT > 0 rotate in (at most `budget` rotations in flight) by evicting the active models with the most
              negative VLT (active longest) that were resident for ≥ min_residency.
  lvf_select with Params.cost_aware: A9.2 "residency-aware lag" (F6, 2026-11-09; references R2 Clockwork §5.3 and
              R8 GreedyDual-Size in reports/registro/referencias.md). A9.1 scores an active model only by how long it
              has been active, so it evicted busy models (F6a H3). A9.2 gives every model the same lag measure, the
              largest lag of its waiting requests at a time t', lag_m(t'), and uses the measured swap time Ĉ_rot
              (c_rot.json, with or without preemption, as the policy runs):
                gain of an inactive model    G_m = lag_m(now + Ĉ_rot(m))  (when its requests can start if it
                                             rotates in now: only demand that still benefits counts, Clockwork)
                cost of evicting an active v K_v = 0 if it has nothing waiting or running; else
                                             max(lag_v(now + Ĉ_rot(v)) of its waiting requests (they wait for it to
                                             come back), and, with preemption, α·ReLU(Ĉ_rot(v) − β_B·SLO_TPOT) for
                                             its running requests, which restart from the prompt)
              m rotates in only if G_m > K_v + margin for every victim taken; victims in increasing K_v per GB freed
              (GreedyDual-Size: evict the one cheapest to bring back per unit of size), then active longest.
  lvf_select with Params.preempt_per_swap: A9.4 (F6.16, D52/D53; reference R10 Shepherd). As A9.2 with the costs
              of a swap without preemption, plus a per-swap choice: for each rotation, saved = waiting requests of the
              incoming model that meet their TTFT deadline only if it starts after the preempting swap time
              (now + Ĉ_rot^P ≤ deadline < now + Ĉ_rot^noP), lost = running requests of its victims (they restart
              from the prompt); preempt iff lost == 0 or saved ≥ λ·lost (λ = Params.preempt_lambda, 3 ≈ Shepherd's
              optimal 3.03). The flag goes to Decision.preempt.
  lvf_select with Params.predictive: A2.3 (F6.16; reference R7). As A9.2, but an active model that expects at least
              one arrival while away (rate · Ĉ_rot ≥ 1) also costs the lag such an arrival takes:
              K_v ≥ ReLU(Ĉ_rot(v) − β_F·SLO_v), SLO_v = its typical TTFT SLO.
  loss_select A3.1 (F6.16; references R9 QLM, R8 GreedyDual-Size): expected deadline loss, current queue only (no
              rate). Gain of an inactive model = its waiting requests still viable if it rotates in now
              (deadline ≥ now + Ĉ_rot); loss of evicting an active model = its waiting requests viable now
              (deadline ≥ now) that would miss while it is away (deadline < now + Ĉ_rot); rotate iff gain − Σ loss
              > θ; victims by loss per GB, then active longest; candidates by gain. No preemption.

Memory: a model needs need_gb (weights + activation headroom + max(R2.1 KV pages, A1.1 reserve), computed by the
caller) of free memory on one GPU. A victim frees free_gb (weights + KV of its running requests). Activations are
only planned into memory measured free now (minus pending activations, R2.1); a rotation evicts now and the incoming
model is activated in a later cycle, once the memory is measured free (reserved models are placed first), as the
existing pressure/fair/throughput strategies do.
"""
import dataclasses
import math
from typing import Dict, List, Optional, Tuple

INF = math.inf


@dataclasses.dataclass
class ReqSnap:
    arrival: float  # wall clock (s)
    slo: Optional[float]  # TTFT SLO of the request (s); None: no deadline (warm-up)
    prompt_len: int = 0
    preempted_at: Optional[float] = None  # set when the request was preempted back to the queue


@dataclasses.dataclass
class ModelSnap:
    name: str
    gpu: Optional[int]  # GPU where it is active; None if not active
    need_gb: float  # free memory needed to activate it
    free_gb: float  # memory its eviction frees
    waiting: List[ReqSnap] = dataclasses.field(default_factory=list)  # in queue order
    running: int = 0
    active_since: Optional[float] = None
    c_at: float = 0.0  # Ĉ_at(m) (s)
    c_rot: float = 0.0  # Ĉ_rot(m) (s): measured swap time, with or without preemption as the policy runs (A9.2)
    c_rot_p: float = 0.0  # Ĉ_rot(m) with preemption (A9.4)
    c_rot_np: float = 0.0  # Ĉ_rot(m) without preemption (A9.4)
    rate: float = 0.0  # arrivals/s over the recent window (A2.3)
    slo_typ: Optional[float] = None  # typical TTFT SLO of its requests (A2.3)
    reserved: bool = False  # victims were evicted for it and it is not active yet: placed first
    cooldown: bool = False  # a rotation for it happened recently: no new rotation for it
    blocked: bool = False  # active but already being evicted this cycle (idle eviction): not a victim

    @property
    def active(self):
        return self.gpu is not None


@dataclasses.dataclass
class Snapshot:
    now: float
    models: Dict[str, ModelSnap]
    gpu_free: Dict[int, float]  # GB free on each GPU now, minus pending activations (R2.1)
    prefill_a: float = 0.0  # p̂ = prefill_a + prefill_b · tokens (estimators.prefill_time)
    prefill_b: float = 0.0
    in_flight: int = 0  # rotations started whose incoming model is not active yet


@dataclasses.dataclass
class Params:
    floor: float = 0.0  # A2.1: requests with slack below it are lost and do not count (PRISM_EDF_FLOOR)
    alpha: float = 3.0  # A9.1 (PRISM_LVF_ALPHA)
    beta_f: float = 0.5  # A9.1 (PRISM_LVF_BETA_F)
    beta_b: float = 0.0  # A9.1 (PRISM_LVF_BETA_B)
    tpot_slo: float = 0.0  # SLO_TPOT for the β_B term (not known to the controller; with β_B = 0 it does not matter)
    budget: int = 1  # rotations in flight at once (PRISM_LVF_BUDGET / PRISM_EDF_BUDGET)
    min_residency: float = 0.0  # A1.3 T_min (PRISM_MIN_RESIDENCY)
    cost_aware: bool = False  # A9.2 (PRISM_LVF_COST_AWARE)
    margin: float = 0.0  # A9.2: G_m must beat K_v by this many seconds (PRISM_LVF_MARGIN)
    preempt: bool = False  # victims are preempted (PRISM_SWAP_PREEMPT): their running requests restart (A9.2)
    preempt_per_swap: bool = False  # A9.4 (PRISM_LVF_PREEMPT=per_swap)
    preempt_lambda: float = 3.0  # A9.4 (PRISM_LVF_PREEMPT_LAMBDA)
    predictive: bool = False  # A2.3 (PRISM_LVF_PREDICTIVE)
    theta: float = 0.0  # A3.1 (PRISM_LOSS_THETA)


@dataclasses.dataclass
class Decision:
    activations: List[Tuple[str, int]] = dataclasses.field(default_factory=list)  # (model, gpu)
    victims: List[Tuple[str, int, str]] = dataclasses.field(default_factory=list)  # (victim, gpu, "<kind> for <m>")
    rotated_for: List[str] = dataclasses.field(default_factory=list)  # models victims were evicted for
    scores: Dict[str, dict] = dataclasses.field(default_factory=dict)  # model -> what the decision used
    unplaced: List[str] = dataclasses.field(default_factory=list)  # waiting models left out this cycle
    preempt: Dict[str, bool] = dataclasses.field(default_factory=dict)  # victim -> preempt it (A9.4); absent = default


def _prefill(tokens, snap):
    return snap.prefill_a + snap.prefill_b * tokens if tokens else 0.0


def request_slacks(m: ModelSnap, snap: Snapshot) -> List[float]:
    """Slack of each waiting request of m with a deadline, in queue order (requests served one after the other)."""
    out, ahead = [], 0.0
    base = 0.0 if m.active else m.c_at
    for r in m.waiting:
        own = _prefill(r.prompt_len, snap)
        if r.slo is not None:
            out.append(r.arrival + r.slo - snap.now - (base + ahead + own))
        ahead += own
    return out


def urgency(m: ModelSnap, snap: Snapshot, p: Params) -> Tuple[float, int, int]:
    """(u_m, viable requests, lost requests): u_m = min slack over the viable ones (+inf if none)."""
    sl = request_slacks(m, snap)
    viable = [s for s in sl if s >= p.floor]
    return (min(viable) if viable else INF), len(viable), len(sl) - len(viable)


def vlt(m: ModelSnap, snap: Snapshot, p: Params) -> float:
    if m.active:
        return -(snap.now - m.active_since) if m.active_since is not None else 0.0
    lag = 0.0
    for r in m.waiting:
        if r.preempted_at is not None:
            lag = max(lag, p.alpha * max(0.0, snap.now - r.preempted_at - p.beta_b * p.tpot_slo))
        elif r.slo is not None:
            lag = max(lag, max(0.0, snap.now - r.arrival - p.beta_f * r.slo))
    return lag


def lag_at(m: ModelSnap, t: float, p: Params) -> float:
    """A9.2: largest lag of m's waiting requests at time t (A9.1's request lag), whether m is active or not."""
    lag = 0.0
    for r in m.waiting:
        if r.preempted_at is not None:
            lag = max(lag, p.alpha * max(0.0, t - r.preempted_at - p.beta_b * p.tpot_slo))
        elif r.slo is not None:
            lag = max(lag, max(0.0, t - r.arrival - p.beta_f * r.slo))
    return lag


def rotation_gain(m: ModelSnap, snap: Snapshot, p: Params) -> float:
    """A9.2 G_m: lag of m's requests when they can start if m rotates in now."""
    return lag_at(m, snap.now + m.c_rot, p)


def eviction_cost(v: ModelSnap, snap: Snapshot, p: Params) -> float:
    """A9.2 K_v: lag that evicting v now imposes on its own requests (they wait one swap for v to come back)."""
    expected = 0.0  # A2.3: an arrival is expected while v is away
    if p.predictive and v.rate * v.c_rot >= 1.0 and v.slo_typ is not None:
        expected = max(0.0, v.c_rot - p.beta_f * v.slo_typ)
    if not v.waiting and not v.running:
        return expected
    cost = max(lag_at(v, snap.now + v.c_rot, p), expected)
    if p.preempt and v.running:
        cost = max(cost, p.alpha * max(0.0, v.c_rot - p.beta_b * p.tpot_slo))
    return cost


def _waiting_inactive(snap: Snapshot) -> List[ModelSnap]:
    return [m for m in snap.models.values() if not m.active and (m.waiting or m.running)]


def _place(order: List[ModelSnap], free: Dict[int, float], dec: Decision) -> List[ModelSnap]:
    """Activate in order into free memory (GPU with the most free memory first); returns the ones that did not fit."""
    left = []
    for m in order:
        gpus = sorted((g for g in free if free[g] >= m.need_gb), key=lambda g: -free[g])
        if gpus:
            free[gpus[0]] -= m.need_gb
            dec.activations.append((m.name, gpus[0]))
        else:
            left.append(m)
    return left


def _rotate(m: ModelSnap, free: Dict[int, float], victims_by_gpu: Dict[int, List[ModelSnap]], kind: str,
            dec: Decision) -> bool:
    """Evict, on one GPU, the first victims of the (already ordered) candidate lists until m fits; the GPU needing the
    fewest victims wins. Returns whether m got room."""
    best = None
    for g, cands in victims_by_gpu.items():
        freed, picked = free.get(g, 0.0), []
        for v in cands:
            if freed >= m.need_gb:
                break
            picked.append(v)
            freed += v.free_gb
        if freed >= m.need_gb and picked and (best is None or len(picked) < len(best[1])):
            best = (g, picked)
    if best is None:
        return False
    g, picked = best
    # the free memory and what the victims free go to m (activated in a later cycle); what is left stays free
    free[g] = max(0.0, free.get(g, 0.0) + sum(v.free_gb for v in picked) - m.need_gb)
    for v in picked:
        victims_by_gpu[g].remove(v)
        dec.victims.append((v.name, g, f"{kind} rotation for {m.name}"))
    dec.rotated_for.append(m.name)
    return True


def _resident_enough(v: ModelSnap, snap: Snapshot, p: Params) -> bool:
    return v.active and not v.blocked and (v.active_since is None or snap.now - v.active_since >= p.min_residency)


def edf_select(snap: Snapshot, p: Params) -> Decision:
    dec = Decision()
    urg = {}
    for m in snap.models.values():
        if m.waiting or m.running or m.active:
            u, nv, nl = urgency(m, snap, p)
            urg[m.name] = u
            dec.scores[m.name] = {"u": None if u == INF else round(u, 3), "viable": nv, "lost": nl,
                                  "active": m.active}
    cands = _waiting_inactive(snap)
    oldest = lambda m: min((r.arrival for r in m.waiting), default=snap.now)
    # models victims were already evicted for come first, whatever their slack (otherwise the freed memory can go
    # back to the victim itself and the rotation is wasted: F6a triage C1 r2, investigation in F06a report)
    reserved = sorted((m for m in cands if m.reserved), key=lambda m: (urg[m.name], oldest(m)))
    viable = sorted((m for m in cands if not m.reserved and urg[m.name] < INF), key=lambda m: urg[m.name])
    lost = sorted((m for m in cands if not m.reserved and urg[m.name] == INF), key=oldest)
    free = dict(snap.gpu_free)
    left = _place(reserved + viable + lost, free, dec)

    budget = p.budget - snap.in_flight
    # victims: no viable waiting request first (+inf; among them no running requests, then active longest), then the
    # latest deadlines
    victims_by_gpu: Dict[int, List[ModelSnap]] = {}
    for v in snap.models.values():
        if _resident_enough(v, snap, p):
            victims_by_gpu.setdefault(v.gpu, []).append(v)
    key = lambda v: (-urg.get(v.name, INF), bool(v.waiting or v.running), v.active_since or 0.0)
    for cands_g in victims_by_gpu.values():
        cands_g.sort(key=key)
    for m in left:
        if budget <= 0:
            dec.unplaced.append(m.name)
            continue
        if m.cooldown:
            dec.unplaced.append(m.name)
            continue
        um = urg[m.name]
        if um < INF:  # viable: anyone whose earliest viable deadline is later
            allowed = {g: [v for v in vs if urg.get(v.name, INF) > um] for g, vs in victims_by_gpu.items()}
        else:  # only lost requests: only models with nothing to do
            allowed = {g: [v for v in vs if not v.waiting and not v.running] for g, vs in victims_by_gpu.items()}
        if _rotate(m, free, allowed, "edf", dec):
            budget -= 1
            taken = {x[0] for x in dec.victims}
            victims_by_gpu = {g: [v for v in vs if v.name not in taken] for g, vs in victims_by_gpu.items()}
        else:
            dec.unplaced.append(m.name)
    return dec


def lvf_select(snap: Snapshot, p: Params) -> Decision:
    if p.cost_aware:
        return _lvf_cost_aware(snap, p)
    dec = Decision()
    lag = {}
    for m in snap.models.values():
        if m.waiting or m.running or m.active:
            lag[m.name] = vlt(m, snap, p)
            dec.scores[m.name] = {"vlt": round(lag[m.name], 3), "active": m.active}
    cands = sorted(_waiting_inactive(snap), key=lambda m: (not m.reserved, -lag[m.name]))
    free = dict(snap.gpu_free)
    left = _place(cands, free, dec)
    if not left:  # contention check: everything that waits fits
        return dec

    budget = p.budget - snap.in_flight
    victims_by_gpu: Dict[int, List[ModelSnap]] = {}
    for v in snap.models.values():
        if _resident_enough(v, snap, p):
            victims_by_gpu.setdefault(v.gpu, []).append(v)
    for cands_g in victims_by_gpu.values():
        cands_g.sort(key=lambda v: lag.get(v.name, 0.0))  # most negative (active longest) first
    for m in left:
        if budget <= 0 or m.cooldown or lag[m.name] <= 0 or not _rotate(m, free, victims_by_gpu, "lvf", dec):
            dec.unplaced.append(m.name)
            continue
        budget -= 1
    return dec


def _lvf_cost_aware(snap: Snapshot, p: Params) -> Decision:
    """A9.2 (see the module docstring)."""
    dec = Decision()
    gain, cost = {}, {}
    for m in snap.models.values():
        if m.active:
            cost[m.name] = eviction_cost(m, snap, p)
            if m.waiting or m.running:
                dec.scores[m.name] = {"vlt": round(lag_at(m, snap.now, p), 3), "k": round(cost[m.name], 3),
                                      "active": True}
        elif m.waiting or m.running:
            gain[m.name] = rotation_gain(m, snap, p)
            dec.scores[m.name] = {"vlt": round(lag_at(m, snap.now, p), 3), "g": round(gain[m.name], 3),
                                  "active": False}
    cands = sorted(_waiting_inactive(snap), key=lambda m: (not m.reserved, -gain[m.name]))
    free = dict(snap.gpu_free)
    left = _place(cands, free, dec)
    if not left:  # contention check: everything that waits fits
        return dec

    budget = p.budget - snap.in_flight
    victims_by_gpu: Dict[int, List[ModelSnap]] = {}
    for v in snap.models.values():
        if _resident_enough(v, snap, p):
            victims_by_gpu.setdefault(v.gpu, []).append(v)
    per_gb = lambda v: cost[v.name] / v.free_gb if v.free_gb > 0 else INF
    for cands_g in victims_by_gpu.values():
        cands_g.sort(key=lambda v: (per_gb(v), v.active_since if v.active_since is not None else 0.0))
    for m in left:
        g = gain[m.name]
        if budget <= 0 or m.cooldown or g <= 0:
            dec.unplaced.append(m.name)
            continue
        allowed = {gpu: [v for v in vs if cost[v.name] + p.margin < g] for gpu, vs in victims_by_gpu.items()}
        n_before = len(dec.victims)
        if not _rotate(m, free, allowed, "lvf", dec):  # same reason text as A9.1 (extract_ovl.py)
            dec.unplaced.append(m.name)
            continue
        if p.preempt_per_swap:
            picked = [snap.models[v[0]] for v in dec.victims[n_before:]]
            choice = preempt_choice(m, picked, snap, p)
            for v in picked:
                dec.preempt[v.name] = choice["preempt"]
            dec.scores[m.name] |= choice
        budget -= 1
        taken = {x[0] for x in dec.victims}
        victims_by_gpu = {gpu: [v for v in vs if v.name not in taken] for gpu, vs in victims_by_gpu.items()}
    return dec


def preempt_choice(m: ModelSnap, victims: List[ModelSnap], snap: Snapshot, p: Params) -> dict:
    """A9.4: preempt the victims of the rotation for m iff they run nothing or saved ≥ λ·lost (Shepherd, R10)."""
    lo, hi = snap.now + m.c_rot_p, snap.now + m.c_rot_np
    saved = sum(1 for r in m.waiting if r.slo is not None and lo <= r.arrival + r.slo < hi)
    lost = sum(v.running for v in victims)
    return {"saved": saved, "lost": lost, "preempt": lost == 0 or saved >= p.preempt_lambda * lost}


def viable_count(m: ModelSnap, t: float) -> int:
    """A3.1: waiting requests of m whose TTFT deadline is not before t."""
    return sum(1 for r in m.waiting if r.slo is not None and r.arrival + r.slo >= t)


def loss_select(snap: Snapshot, p: Params) -> Decision:
    """A3.1 (see the module docstring)."""
    dec = Decision()
    gain, loss = {}, {}
    for m in snap.models.values():
        if m.active:
            loss[m.name] = viable_count(m, snap.now) - viable_count(m, snap.now + m.c_rot)
            if m.waiting or m.running:
                dec.scores[m.name] = {"loss": loss[m.name], "active": True}
        elif m.waiting or m.running:
            gain[m.name] = viable_count(m, snap.now + m.c_rot)
            dec.scores[m.name] = {"gain": gain[m.name], "active": False}
    oldest = lambda m: min((r.arrival for r in m.waiting), default=snap.now)
    cands = sorted(_waiting_inactive(snap), key=lambda m: (not m.reserved, -gain[m.name], oldest(m)))
    free = dict(snap.gpu_free)
    left = _place(cands, free, dec)
    if not left:
        return dec
    budget = p.budget - snap.in_flight
    victims_by_gpu: Dict[int, List[ModelSnap]] = {}
    for v in snap.models.values():
        if _resident_enough(v, snap, p):
            victims_by_gpu.setdefault(v.gpu, []).append(v)
    per_gb = lambda v: loss[v.name] / v.free_gb if v.free_gb > 0 else INF
    for cands_g in victims_by_gpu.values():
        cands_g.sort(key=lambda v: (per_gb(v), v.active_since if v.active_since is not None else 0.0))
    for m in left:
        g = gain[m.name]
        if budget <= 0 or m.cooldown or g <= p.theta:
            dec.unplaced.append(m.name)
            continue
        best = None  # fewest lost requests on one GPU, then fewest victims
        for gpu, vs in victims_by_gpu.items():
            freed, picked = free.get(gpu, 0.0), []
            for v in vs:
                if freed >= m.need_gb:
                    break
                picked.append(v)
                freed += v.free_gb
            lost = sum(loss[v.name] for v in picked)
            if freed >= m.need_gb and picked and g - lost > p.theta:
                if best is None or (lost, len(picked)) < (best[1], len(best[2])):
                    best = (gpu, lost, picked)
        if best is None:
            dec.unplaced.append(m.name)
            continue
        gpu, lost, picked = best
        free[gpu] = max(0.0, free.get(gpu, 0.0) + sum(v.free_gb for v in picked) - m.need_gb)
        for v in picked:
            victims_by_gpu[gpu].remove(v)
            dec.victims.append((v.name, gpu, f"loss rotation for {m.name}"))
        dec.rotated_for.append(m.name)
        dec.scores[m.name]["lost"] = lost
        budget -= 1
    return dec
