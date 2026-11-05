"""Check a level's workload against its specification (F3 acceptance: rates ±5%, CV ±10%, popularity preserved).

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/workload_check.py <level dir> [...] [--seeds 20] [--json]

The specification comes from the level's own summary.json "args" (overload_load.py or workloads.py emit), so the
same check runs on a local emit and on a dry-run level from the cluster. Two readings per statistic:
  realized  the requests of this level (one seed): what the run actually sent
  process   the mean over --seeds seeds of the same arguments: what the generator promises (a single 600-s level
            of a bursty process cannot be within ±5% of its mean rate: its count's SD is ~CV x sqrt(N))
Statistics by pattern:
  all       total rate vs target (per-model rate x models, total rate, or the trace's count / span)
  constant  per-model CV (median) vs --cv; shares vs uniform (or --model-rates)
  bursty    per-model CV (median) vs the IPP formula (workloads.ipp_cv)
  zipf_drift  share of each rank in each drift period, pooled, vs Zipf(alpha); total rate
  diurnal   mean rate and the peak/trough ratio of 1/10-period bins vs (1 + A) / (1 - A); fixed Zipf shares
  trace     same requests as the trace (count per entity), popularity order of the entities kept
  classes   batch fraction vs --batch-frac (absolute ±0.02)
"""
import argparse
import json
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workloads as w  # noqa: E402

TOL_RATE, TOL_CV, TOL_FRAC = 0.05, 0.10, 0.02


def ns(args):
    a = argparse.Namespace(**args)
    for k, v in vars(build_defaults()).items():
        if not hasattr(a, k):
            setattr(a, k, v)
    return a


def build_defaults():
    p = argparse.ArgumentParser()
    w.add_args(p)
    a = p.parse_args(["--models", "m"])
    a.time_scale = 1.0
    return a


def cv(ts):
    g = np.diff(np.sort(ts))
    return float(g.std() / g.mean()) if len(g) > 2 and g.mean() > 0 else None


def stats(a, reqs):
    """reqs: [(t, model, pl, ol, cls)] -> dict of statistics, with the spec targets."""
    T = a.duration
    t = np.array([r[0] for r in reqs])
    per = {m: np.array([r[0] for r in reqs if r[1] == m]) for m in a.models}
    out = {"requests": len(reqs), "rate_total": len(reqs) / T}
    if a.pattern == "constant":
        rates = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.model_rates)
        out["target_rate_total"] = sum(rates.get(m, a.rate) for m in a.models) / (a.groups or 1)
        out["target_cv"] = a.cv if a.groups == 1 else None
    elif a.pattern == "bursty":
        out["target_rate_total"] = a.rate * len(a.models)
        out["target_cv"] = w.ipp_cv(a.rate, a.burst_on, a.burst_off)
    elif a.pattern in ("zipf_drift", "diurnal"):
        out["target_rate_total"] = a.total_rate
        out["target_cv"] = a.cv if a.pattern == "zipf_drift" else None
    if out.get("target_cv"):
        cvs = [c for c in (cv(x) for x in per.values()) if c]
        out["cv_median"] = statistics.median(cvs) if cvs else None
    if a.pattern == "zipf_drift":
        orders = w.drift_orders(len(a.models), a.drift_period, T)
        cnt = np.zeros(len(a.models))
        for k, o in enumerate(orders):
            for rank, i in enumerate(o):
                x = per[a.models[i]]
                cnt[rank] += ((x >= k * a.drift_period) & (x < (k + 1) * a.drift_period)).sum()
        out["rank_shares"] = list(cnt / cnt.sum())
        out["target_rank_shares"] = list(w.zipf_shares(len(a.models), a.zipf_alpha))
    if a.pattern == "diurnal":
        P = a.diurnal_period
        ph = (t % P) / P
        trough = ((ph < 0.05) | (ph >= 0.95)).sum()
        peak = ((ph >= 0.45) & (ph < 0.55)).sum()
        out["peak_trough"] = peak / max(trough, 1)
        # mean of 1 - A cos over the +-5% bins, peak / trough
        x = np.linspace(-0.05, 0.05, 201)
        out["target_peak_trough"] = float(np.mean(1 + a.diurnal_amp * np.cos(2 * np.pi * x)) /
                                          np.mean(1 - a.diurnal_amp * np.cos(2 * np.pi * x)))
    if a.pattern == "trace":
        _, rows = w.read_trace(a.trace)
        top = w.entity_ranks(rows)[:len(a.models)]
        want = [sum(r[1] == e for r in rows if r[0] * a.time_scale < T or True) for e in top]
        got = [len(per[m]) for m in a.models]
        out["trace_counts_match"] = want == got
        out["popularity_order_ok"] = got == sorted(got, reverse=True)
        out["target_rate_total"] = sum(want) / T
    if a.batch_frac:
        out["batch_frac"] = sum(r[4] == "batch" for r in reqs) / len(reqs)
        out["target_batch_frac"] = a.batch_frac
    return out


def verdict(s):
    v = {}
    if s.get("target_rate_total"):
        v["rate"] = abs(s["rate_total"] / s["target_rate_total"] - 1) <= TOL_RATE
    if s.get("target_cv") and s.get("cv_median"):
        v["cv"] = abs(s["cv_median"] / s["target_cv"] - 1) <= TOL_CV
    if "rank_shares" in s:
        v["popularity"] = list(np.argsort(-np.array(s["rank_shares"]), kind="stable")) == list(range(len(s["rank_shares"])))
    if "peak_trough" in s:
        v["diurnal_swing"] = abs(s["peak_trough"] / s["target_peak_trough"] - 1) <= TOL_CV
    if "trace_counts_match" in s:
        v["trace"] = s["trace_counts_match"] and s["popularity_order_ok"]
    if "batch_frac" in s:
        v["classes"] = abs(s["batch_frac"] - s["target_batch_frac"]) <= TOL_FRAC
    return v


def check(level, seeds):
    summ = json.load(open(os.path.join(level, "summary.json")))
    a = ns(summ["args"])
    rows = json.load(open(os.path.join(level, "requests.json")))
    reqs = [(r["arrival"], r.get("workload_model", r["model"]), r["prompt_len"], r["output_len"],
             r.get("slo_class", "interactive")) for r in rows]
    if a.pattern == "trace":
        a.duration = summ["args"]["duration"]
    real = stats(a, reqs)
    proc = []
    if a.pattern not in ("trace",):
        for sd in range(seeds):
            b = ns(dict(vars(a), seed=1000 + sd))
            proc.append(stats(b, w.build(b)[0]))
    mean = {}
    for k in proc[0] if proc else []:
        vals = [p[k] for p in proc]
        if all(isinstance(x, (int, float)) and x is not None for x in vals):
            mean[k] = float(np.mean(vals))
        elif all(isinstance(x, list) for x in vals):
            mean[k] = list(np.mean(np.array(vals), axis=0))
        else:
            mean[k] = vals[0]
    return {"level": level, "pattern": a.pattern, "realized": real, "realized_ok": verdict(real),
            "process": mean, "process_ok": verdict(mean) if mean else {}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("levels", nargs="+")
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    res = [check(d, a.seeds) for d in a.levels]
    if a.json:
        print(json.dumps(res, indent=1, default=float))
        return
    for r in res:
        R, P = r["realized"], r["process"]
        f = lambda x: "-" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))
        print(f"{r['level']} [{r['pattern']}]")
        print(f"  realized: rate {f(R['rate_total'])} / target {f(R.get('target_rate_total'))}, "
              f"cv {f(R.get('cv_median'))} / {f(R.get('target_cv'))}"
              + (f", peak/trough {f(R['peak_trough'])} / {f(R['target_peak_trough'])}" if 'peak_trough' in R else "")
              + (f", batch {f(R['batch_frac'])}" if 'batch_frac' in R else "") + f"  -> {r['realized_ok']}")
        if P:
            print(f"  process : rate {f(P['rate_total'])}, cv {f(P.get('cv_median'))}"
                  + (f", peak/trough {f(P['peak_trough'])}" if 'peak_trough' in P else "")
                  + (f", rank shares {[round(x, 3) for x in P['rank_shares']]}" if 'rank_shares' in P else "")
                  + f"  -> {r['process_ok']}")


if __name__ == "__main__":
    main()
