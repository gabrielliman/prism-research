"""Workload construction for the F3 catalogue (PLANO_AGENTE.md section 5): pure functions, no server, no network.

overload_load.py builds every synthetic and trace workload through build(); `python3 polyaxon/workloads.py emit ...`
takes the same arguments and only writes <out>/requests.json + summary.json (no server), so workload_stats.py and the
offline checks (workload_check.py) see exactly what a job would send.

Arrival patterns (--pattern), all open loop, per model, with a fixed seed:
  constant    rate --rate per model (or --model-rates), Gamma inter-arrivals with CV --cv (C1-C5, as before)
  zipf_drift  C6: total rate --total-rate split by Zipf(--zipf-alpha) shares over the ranks; every --drift-period s the
              models at ranks j and j+1 swap, j = 0, 1, ..., n-2, 0, ... (gradual rotation: after n-1 swaps the
              most popular model is the least popular and every other model rose one rank). Within a period the
              per-model rate is constant; arrivals are a renewal process with CV --cv on the model's cumulative
              intensity (time rescaling), so the shape (CV) does not depend on the rate.
  bursty      C7: per model an on/off Markov-modulated Poisson process (interrupted Poisson, IPP): exponential on
              periods (mean --burst-on s) with rate lambda_on, silent off periods (mean --burst-off s), independent
              per model, started in the stationary state; lambda_on chosen so the mean rate is --rate. Inter-arrival
              SCV = 1 + 2 lambda_on w1 / (w1 + w2)^2, w1 = 1/on, w2 = 1/off (Fischer and Meier-Hellstern, "The MMPP
              cookbook", 1993), reported as the target CV.
  diurnal     C8: total rate lambda(t) = --total-rate * (1 - A cos(2 pi t / P)), A = --diurnal-amp, P = --diurnal-period
              (one compressed "day"; starts at the trough), fixed popularity (Zipf(--zipf-alpha); alpha 0 = uniform),
              renewal with CV --cv on the cumulative intensity.
  trace       T2-T5: a normalized trace (--trace FILE, written by trace_adapt.py): arrival, entity, prompt_len,
              output_len. The --trace-entities N most frequent entities map to --models in rank order (rank rule of
              section 5.3, item 3); arrivals are multiplied by --time-scale and cut at --duration (default: the span).

Lengths (--lengths): "uniform" (--input-range/--output-range, C1-C5) or "empirical:<file>": (prompt, output) pairs
drawn jointly, with replacement, from a normalized trace's lengths (keeps their correlation), then capped at
--max-prompt / --max-output; the capped fractions go to the summary (section 5.3, item 5). Trace patterns keep the
trace's own lengths (also capped).

SLO classes (C9, --batch-frac f): each request is "batch" with probability f (own RNG stream, so the arrivals do not
change with f), "interactive" otherwise. Interactive requests keep the SLO of --slo-spec / --slo-ttft; batch requests
get TTFT SLO --batch-slo-ttft and no TPOT limit (D19, provisional classes: S4 in slo_metrics.py).

Seeds: one numpy Generator per purpose (arrivals, lengths, classes) derived from --seed, so changing one factor does
not reshuffle the others.
"""
import argparse
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter

import numpy as np

STREAM_ARRIVALS, STREAM_LENGTHS, STREAM_CLASSES = 0, 1, 2


def rngs(seed):
    ss = np.random.SeedSequence(seed)
    a, l, c = ss.spawn(3)
    return np.random.default_rng(a), np.random.default_rng(l), np.random.default_rng(c)


# ---- arrival processes ------------------------------------------------------------------------------------------

def renewal_on_intensity(rng, grid, cum, cv):
    """Arrival times of a renewal process with unit-mean Gamma gaps (CV cv) in operational time, mapped back through
    the cumulative intensity cum (piecewise linear on grid): constant intensity gives the usual Gamma process."""
    total = cum[-1]
    if total <= 0:
        return np.array([])
    k = 1.0 / cv ** 2
    n_guess = int(total + 10 * math.sqrt(total) * max(cv, 1) + 20)
    ops = np.cumsum(rng.gamma(k, 1.0 / k, n_guess))
    while ops[-1] < total:
        ops = np.concatenate([ops, ops[-1] + np.cumsum(rng.gamma(k, 1.0 / k, n_guess))])
    ops = ops[ops < total]
    return np.interp(ops, cum, grid)


def cumulative(rate_fn, duration, dt=0.5):
    grid = np.linspace(0.0, duration, int(math.ceil(duration / dt)) + 1)
    mid = (grid[:-1] + grid[1:]) / 2
    cum = np.concatenate([[0.0], np.cumsum(rate_fn(mid) * np.diff(grid))])
    return grid, cum


def ipp_lambda_on(rate, on, off):
    return rate * (on + off) / on


def ipp_cv(rate, on, off):
    w1, w2 = 1.0 / on, 1.0 / off
    return math.sqrt(1 + 2 * ipp_lambda_on(rate, on, off) * w1 / (w1 + w2) ** 2)


def ipp_times(rng, rate, on, off, duration):
    lam = ipp_lambda_on(rate, on, off)
    t, out = 0.0, []
    is_on = rng.random() < on / (on + off)
    while t < duration:
        stay = rng.exponential(on if is_on else off)
        if is_on:
            s = t + rng.exponential(1.0 / lam)
            while s < min(t + stay, duration):
                out.append(s)
                s += rng.exponential(1.0 / lam)
        t += stay
        is_on = not is_on
    return np.array(out)


def zipf_shares(n, alpha):
    w = np.arange(1, n + 1, dtype=float) ** -alpha
    return w / w.sum()


def drift_orders(n, period, duration):
    """Rank order (list of model indexes, most popular first) in each drift period: swap ranks j, j+1 with
    j = 0, 1, ..., n-2, 0, ..."""
    order, orders = list(range(n)), []
    for k in range(int(math.ceil(duration / period))):
        orders.append(list(order))
        j = k % (n - 1)
        order[j], order[j + 1] = order[j + 1], order[j]
    return orders


def arrivals(a, rng):
    """[(time, model)] for the synthetic patterns."""
    n, T = len(a.models), a.duration
    out = []
    if a.pattern == "constant":
        rates = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.model_rates)
        groups = [a.models[i * n // a.groups:(i + 1) * n // a.groups] for i in range(a.groups)]
        for g, members in enumerate(groups):
            for m in members:
                rate, t = rates.get(m, a.rate), 0.0
                while True:  # same draws as overload_load.py before F3 (C1-C5 keep their hash)
                    t += rng.gamma(1.0 / a.cv ** 2, a.cv ** 2 / rate)
                    if t >= T:
                        break
                    if a.groups > 1 and int(t // a.phase) % a.groups != g:
                        continue
                    out.append((t, m))
        return out
    if a.pattern == "zipf_drift":
        shares = zipf_shares(n, a.zipf_alpha)
        orders = drift_orders(n, a.drift_period, T)
        for i, m in enumerate(a.models):
            per = np.array([a.total_rate * shares[o.index(i)] for o in orders])
            fn = lambda t, per=per: per[np.minimum((t // a.drift_period).astype(int), len(per) - 1)]
            out += [(t, m) for t in renewal_on_intensity(rng, *cumulative(fn, T), a.cv)]
        return out
    if a.pattern == "diurnal":
        shares = zipf_shares(n, a.zipf_alpha)
        for i, m in enumerate(a.models):
            fn = lambda t, s=shares[i]: s * a.total_rate * (1 - a.diurnal_amp * np.cos(2 * np.pi * t / a.diurnal_period))
            out += [(t, m) for t in renewal_on_intensity(rng, *cumulative(fn, T), a.cv)]
        return out
    if a.pattern == "bursty":
        for m in a.models:
            out += [(t, m) for t in ipp_times(rng, a.rate, a.burst_on, a.burst_off, T)]
        return out
    raise ValueError(a.pattern)


# ---- traces and lengths -----------------------------------------------------------------------------------------

def read_trace(path):
    """Normalized trace (trace_adapt.py): '# key: value' header lines, then CSV arrival,entity,prompt_len,output_len."""
    meta, rows = {}, []
    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as f:
        lines = []
        for ln in f:
            if ln.startswith("#"):
                k, _, v = ln[1:].partition(":")
                meta[k.strip()] = v.strip()
            else:
                lines.append(ln)
    for r in csv.DictReader(lines):
        rows.append((float(r["arrival"]), r["entity"], int(r["prompt_len"]), int(r["output_len"])))
    return meta, rows


def write_trace(path, rows, meta):
    with (gzip.open(path, "wt") if path.endswith(".gz") else open(path, "w")) as f:
        for k, v in meta.items():
            f.write(f"# {k}: {v}\n")
        w = csv.writer(f)
        w.writerow(["arrival", "entity", "prompt_len", "output_len"])
        for t, e, p, o in rows:
            w.writerow([f"{t:.3f}", e, p, o])


def entity_ranks(rows):
    return [e for e, _ in sorted(Counter(r[1] for r in rows).items(), key=lambda kv: (-kv[1], kv[0]))]


def trace_requests(a):
    meta, rows = read_trace(a.trace)
    top = entity_ranks(rows)[:len(a.models)]
    model_of = dict(zip(top, a.models))
    span = max(r[0] for r in rows) * a.time_scale
    T = a.duration or span  # default: the whole trace (last arrival included)
    out = [(t * a.time_scale, model_of[e], p, o) for t, e, p, o in rows
           if e in model_of and (t * a.time_scale < T or not a.duration)]
    return out, T


def length_table(spec):
    if spec.startswith("empirical:"):
        _, rows = read_trace(spec.split(":", 1)[1])
        return np.array([(r[2], r[3]) for r in rows])
    return None


def cap(pl, ol, a, capped):
    if a.max_prompt and pl > a.max_prompt:
        pl, capped["prompt"] = a.max_prompt, capped["prompt"] + 1
    if a.max_output and ol > a.max_output:
        ol, capped["output"] = a.max_output, capped["output"] + 1
    return max(1, pl), max(1, ol)


def build(a):
    """[(arrival, model, prompt_len, output_len, slo_class)] sorted by arrival, and info for the summary."""
    r_arr, r_len, r_cls = rngs(a.seed)
    capped = {"prompt": 0, "output": 0}
    info = {}
    if a.pattern == "trace":
        reqs, a.duration = trace_requests(a)
        reqs = [(t, m, *cap(p, o, a, capped)) for t, m, p, o in reqs]
    else:
        arr = sorted(arrivals(a, r_arr))
        tab = length_table(a.lengths)
        reqs = []
        if a.pattern == "constant" and tab is None:
            # pre-F3 draw order (one RNG, lengths drawn per arrival in model order) keeps the C1-C5 hashes
            reqs = legacy_constant(a)
        else:
            for t, m in arr:
                if tab is None:
                    pl = int(r_len.integers(a.input_range[0], a.input_range[1] + 1))
                    ol = int(r_len.integers(a.output_range[0], a.output_range[1] + 1))
                else:
                    pl, ol = (int(x) for x in tab[r_len.integers(len(tab))])
                reqs.append((t, m, *cap(pl, ol, a, capped)))
        if a.pattern == "bursty":
            info["target_cv"] = ipp_cv(a.rate, a.burst_on, a.burst_off)
    reqs.sort()
    cls = ["batch" if u < a.batch_frac else "interactive" for u in r_cls.random(len(reqs))] if a.batch_frac else \
        ["interactive"] * len(reqs)
    info["capped_frac"] = {k: v / max(1, len(reqs)) for k, v in capped.items()}
    return [(*r, c) for r, c in zip(reqs, cls)], info


def legacy_constant(a):
    """overload_load.py's pre-F3 generator, verbatim: one RNG, lengths drawn right after each kept arrival."""
    rng = np.random.default_rng(a.seed)
    n = len(a.models)
    groups = [a.models[i * n // a.groups:(i + 1) * n // a.groups] for i in range(a.groups)]
    rates = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.model_rates)
    reqs = []
    for g, members in enumerate(groups):
        for m in members:
            rate, t = rates.get(m, a.rate), 0.0
            while True:
                t += rng.gamma(1.0 / a.cv ** 2, a.cv ** 2 / rate)
                if t >= a.duration:
                    break
                if a.groups > 1 and int(t // a.phase) % a.groups != g:
                    continue
                pl = int(rng.integers(a.input_range[0], a.input_range[1] + 1))
                ol = int(rng.integers(a.output_range[0], a.output_range[1] + 1))
                reqs.append((t, m, pl, ol))
    return reqs


# ---- CLI ---------------------------------------------------------------------------------------------------------

def add_args(p):
    """Workload arguments shared by overload_load.py and the emit command."""
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--pattern", default="constant", choices=["constant", "zipf_drift", "bursty", "diurnal", "trace"])
    p.add_argument("--rate", type=float)
    p.add_argument("--total-rate", type=float)
    p.add_argument("--model-rates", nargs="*", default=[])
    p.add_argument("--duration", type=float)
    p.add_argument("--input-range", type=int, nargs=2, default=[256, 1024])
    p.add_argument("--output-range", type=int, nargs=2, default=[128, 512])
    p.add_argument("--lengths", default="uniform")
    p.add_argument("--max-prompt", type=int, default=0)
    p.add_argument("--max-output", type=int, default=0)
    p.add_argument("--cv", type=float, default=1.0)
    p.add_argument("--groups", type=int, default=1)
    p.add_argument("--phase", type=float, default=150)
    p.add_argument("--zipf-alpha", type=float, default=1.0)
    p.add_argument("--drift-period", type=float, default=60)
    p.add_argument("--burst-on", type=float, default=10)
    p.add_argument("--burst-off", type=float, default=20)
    p.add_argument("--diurnal-amp", type=float, default=0.8)
    p.add_argument("--diurnal-period", type=float, default=1200)
    p.add_argument("--trace")
    p.add_argument("--batch-frac", type=float, default=0.0)
    p.add_argument("--batch-slo-ttft", type=float, default=60.0)
    p.add_argument("--seed", type=int, default=42)


def check_args(p, a):
    if a.pattern in ("constant", "bursty") and (a.rate is None or a.duration is None):
        p.error(f"--pattern {a.pattern} needs --rate and --duration")
    if a.pattern in ("zipf_drift", "diurnal") and (a.total_rate is None or a.duration is None):
        p.error(f"--pattern {a.pattern} needs --total-rate and --duration")
    if a.pattern == "zipf_drift" and len(a.models) < 2:
        p.error("zipf_drift needs at least 2 models")
    if a.pattern == "trace" and not a.trace:
        p.error("--pattern trace needs --trace")


def emit(argv):
    p = argparse.ArgumentParser(prog="workloads.py emit")
    add_args(p)
    p.add_argument("--time-scale", type=float, default=1.0)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    check_args(p, a)
    reqs, info = build(a)
    rows = [{"id": str(i), "model": m, "arrival": round(t, 3), "prompt_len": pl, "output_len": ol, "slo_class": c,
             "status": "not_sent"} for i, (t, m, pl, ol, c) in enumerate(reqs)]
    os.makedirs(a.out, exist_ok=True)
    json.dump(rows, open(os.path.join(a.out, "requests.json"), "w"))
    json.dump({"args": vars(a), "sent": 0, "emitted": len(rows), "workload_info": info},
              open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    print(f"{a.out}: {len(rows)} requests over {a.duration:.0f} s")


if __name__ == "__main__":
    if sys.argv[1:2] != ["emit"]:
        sys.exit(__doc__)
    emit(sys.argv[2:])
