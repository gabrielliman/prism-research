"""Estimators for the deadline-aware policies (F2.3–F2.5, PLANO_AGENTE.md section 4): pure functions and small
state objects, no I/O, so the policies' decision functions stay testable with hand-built states (section 0.4).

  activation_cost(weights_gb, ahead, coef)      Ĉ_at: a + b·W + c·ahead, coef from reports/data/F02/cat/cat_model.json
  prefill_time(tokens, coef)                    p̂: prefill time of a batch of `tokens` prompt tokens, a + b·tokens
                                                (per model, from polyaxon/iso_fit.py, reports/registro/latencia_ref.json)
  queue_time(prompt_lens_ahead, coef, batch_tokens)  q̂_r: prefill of the requests ahead in the model's queue, packed
                                                in batches of up to batch_tokens prompt tokens (SGLang's chunked prefill
                                                budget), one batch after the other
  queue_time_hybrid(...)                        q̂_r + p̂_r: observed first-token rate when the model has enough recent
                                                completions, else the prefill sum (F2.5, decision D17)
  rotation_cost(weights_gb, table)              Ĉ_rot: real swap time (decision -> entering model ready), measured in
                                                F5.0a (reports/registro/c_rot.json), by weights, linear between sizes
  load_rotation_table(path, preempt)            that table, with or without preemption, or None (A9.2, F6)
  RateEstimator                                 λ̂_m: exponentially weighted arrival rate over a short and a long
                                                window; the short one is used while it is well above (a burst) or,
                                                with symmetric=True (default), well below (a lull) the long one
"""
import math


def activation_cost(weights_gb, ahead, coef):
    return coef["a"] + coef["b"] * weights_gb + coef["c"] * ahead


def rotation_cost(weights_gb, table):
    """Ĉ_rot(m): table {weights_gb: seconds}; linear between the measured sizes, constant outside them."""
    pts = sorted(table.items())
    if weights_gb <= pts[0][0]:
        return pts[0][1]
    for (w0, c0), (w1, c1) in zip(pts, pts[1:]):
        if weights_gb <= w1:
            return c0 + (c1 - c0) * (weights_gb - w0) / (w1 - w0)
    return pts[-1][1]


def load_rotation_table(path, preempt):
    """{weights_gb: Ĉ_rot} from c_rot.json (F5.0a): with preemption the 'por_pesos_gb' c_rot (preempted victim's exit
    + a controller cycle + Ĉ_at), without it the measured median of 'sem_preempcao'. None if the file is missing."""
    import json
    import os
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    src = d["por_pesos_gb"] if preempt else d["sem_preempcao"]["por_pesos_gb"]
    return {float(w): float(v["c_rot"]) for w, v in src.items()}


def prefill_time(tokens, coef):
    return coef["prefill_a"] + coef["prefill_b"] * tokens


def queue_time(prompt_lens_ahead, coef, batch_tokens=8192):
    t, batch = 0.0, 0
    for n in prompt_lens_ahead:
        if batch and batch + n > batch_tokens:
            t += prefill_time(batch, coef)
            batch = 0
        batch += n
    return t + (prefill_time(batch, coef) if batch else 0.0)


def queue_time_hybrid(prompt_lens_ahead, own_prompt_len, coef, first_tokens_in_window, window_s=30.0,
                      min_samples=10):
    """q̂_r + p̂_r (time to the first token of a request that joins the queue now, its model active). With at least
    min_samples first tokens of this model in the last window_s seconds, (requests ahead + 1) / observed first-token
    rate, which sees decode interference and the other models' share of the GPU; otherwise the prefill sum
    queue_time + prefill_time. F2.5 (reports/data/F02/estimadores): the prefill sum alone was 35 s off at the median
    under compute overload (C5), the observed rate alone up to 18 s off with few completions."""
    if first_tokens_in_window >= min_samples:
        return (len(prompt_lens_ahead) + 1) / (first_tokens_in_window / window_s)
    return queue_time(prompt_lens_ahead, coef) + prefill_time(own_prompt_len, coef)


class RateEstimator:
    """Arrival rate of one model (req/s) from its arrival times, updated in O(1) per arrival or query.

    Each window keeps an exponentially decaying count c (decay e^(−Δt/τ)); c/τ estimates the rate. With
    burst_ratio r, the estimate is the short window's while it exceeds r × the long window's (or, symmetric, falls
    below it / r), else the long one.
    Early on (elapsed time e not ≫ τ) each count is divided by τ(1 − e^(−e/τ)), the weight the window has had."""

    def __init__(self, short_s=10.0, long_s=60.0, burst_ratio=2.0, start=None, symmetric=True):
        self.taus = (short_s, long_s)
        self.burst_ratio = burst_ratio
        self.symmetric = symmetric  # also follow the short window when it falls well below the long one (a lull)
        self.counts = [0.0, 0.0]
        self.t = start
        self.start = start

    def _decay(self, now):
        if self.t is None:
            self.t = self.start = now
            return
        dt = max(0.0, now - self.t)
        self.counts = [c * math.exp(-dt / tau) for c, tau in zip(self.counts, self.taus)]
        self.t = now

    def arrival(self, now, n=1):
        self._decay(now)
        self.counts = [c + n for c in self.counts]

    def rates(self, now):
        self._decay(now)
        elapsed = max(now - self.start, 1e-9)
        # an exponential window of length τ observed for e < τ seconds has weight τ(1 − e^(−e/τ)), not τ
        return tuple(c / (tau * (1 - math.exp(-elapsed / tau))) for c, tau in zip(self.counts, self.taus))

    def rate(self, now):
        short, long_ = self.rates(now)
        if short > self.burst_ratio * long_ or (self.symmetric and short * self.burst_ratio < long_):
            return short
        return long_

    def expected_arrivals(self, now, horizon_s):
        return self.rate(now) * horizon_s
