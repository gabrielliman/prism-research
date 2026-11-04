"""Fit the reference latencies (F2.10) and the prefill estimator p̂ (F2.4) from iso_latency.py runs.

Usage: python3 polyaxon/iso_fit.py <dest dir> <suite line outputs dir> [...]
       e.g. <dl>/f2-iso/outputs/iso_8b (holds configs/iso_lat.json and iso_lat/r<k>/iso.json)

Per model (model_path of configs/iso_lat.json):
  TTFT_iso(m, L) = ttft_a + ttft_b·L      median (L1) regression on the "ttft" phase (one request at a time)
  p̂(m, N)       = prefill_a + prefill_b·N  median regression of a batch's prefill time on its prompt tokens N: the
                                           "ttft" requests (N = L) and, per burst of k requests of length L, the
                                           largest TTFT of the burst (N = k·L; they are prefilled together)
  TPOT_iso(m)    = median TPOT with 1 stream (tpot_iso) and with 8 (tpot_iso_b8)
Errors are out of sample: each repetition is predicted from a fit on the others (median relative error).
Writes <dest>/latencia_ref.json (what slo_metrics.py reads as reports/registro/latencia_ref.json) and
<dest>/iso_fit.md. Needs numpy (/mnt/scratch/scheduler/opt-env/bin/python).
"""
import glob
import json
import os
import sys

import numpy as np


def l1(x, y):
    X = np.column_stack([np.ones(len(x)), x])
    c = np.linalg.lstsq(X, y, rcond=None)[0]
    for _ in range(100):
        w = 1 / np.maximum(np.abs(y - X @ c), 1e-4)
        c = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
    return c


def points(rows):
    """(ttft points: L, ttft), (prefill points: N, time) of one repetition."""
    ok = [r for r in rows if r["ok"]]
    tt = [(r["prompt_len"], r["ttft"]) for r in ok if r["phase"] == "ttft"]
    pre = list(tt)
    burst = [r for r in ok if r["phase"] == "burst"]
    i = 0
    while i < len(burst):  # rows of one burst are consecutive: same group k
        k = burst[i]["group"]
        b = burst[i:i + k]
        pre.append((k * b[0]["prompt_len"], max(r["ttft"] for r in b)))
        i += k
    return tt, pre


def loo(reps, which):
    """Median relative error of each repetition's points predicted by a fit on the other repetitions."""
    errs = []
    for i in range(len(reps)):
        train = [p for j, r in enumerate(reps) if j != i for p in r[which]]
        if not train:
            continue
        a, b = l1(np.array([p[0] for p in train], float), np.array([p[1] for p in train], float))
        errs += [abs(a + b * x - y) / y for x, y in reps[i][which]]
    return float(np.median(errs)) if errs else None, float(np.quantile(errs, 0.9)) if errs else None


def main():
    dest, dirs = sys.argv[1], sys.argv[2:]
    os.makedirs(dest, exist_ok=True)
    ref, lines = {}, ["# Latências de referência e estimador de prefill (gerado por `polyaxon/iso_fit.py`)", ""]
    for d in dirs:
        path = json.load(open(os.path.join(d, "configs", "iso_lat.json")))[0]["model_path"]
        runs = sorted(glob.glob(os.path.join(d, "iso_lat", "r*", "iso.json")))
        reps, tpot1, tpot8, failed = [], [], [], 0
        for f in runs:
            rows = json.load(open(f))["rows"]
            failed += sum(not r["ok"] for r in rows)
            tt, pre = points(rows)
            reps.append({"tt": tt, "pre": pre})
            tpot1 += [r["tpot"] for r in rows if r["ok"] and r["phase"] == "tpot" and r["group"] == 1]
            tpot8 += [r["tpot"] for r in rows if r["ok"] and r["phase"] == "tpot" and r["group"] == 8]
        tt = [p for r in reps for p in r["tt"]]
        pre = [p for r in reps for p in r["pre"]]
        ta, tb = l1(np.array([p[0] for p in tt], float), np.array([p[1] for p in tt], float))
        pa, pb = l1(np.array([p[0] for p in pre], float), np.array([p[1] for p in pre], float))
        e_tt, e_pre = loo(reps, "tt"), loo(reps, "pre")
        ref[path] = {"ttft_a": float(ta), "ttft_b": float(tb), "tpot_iso": float(np.median(tpot1)),
                     "tpot_iso_b8": float(np.median(tpot8)), "prefill_a": float(pa), "prefill_b": float(pb),
                     "reps": len(runs), "failed_requests": failed,
                     "ttft_err_median": e_tt[0], "ttft_err_p90": e_tt[1], "prefill_err_median": e_pre[0],
                     "prefill_err_p90": e_pre[1],
                     "tpot_iso_cv_between_reps": None}
        per_rep1 = [float(np.median([r["tpot"] for r in json.load(open(f))["rows"] if r["ok"] and r["phase"] == "tpot"
                                     and r["group"] == 1])) for f in runs]
        if len(per_rep1) > 1:
            ref[path]["tpot_iso_cv_between_reps"] = float(np.std(per_rep1) / np.mean(per_rep1))
        by_len = {}
        for L, y in tt:
            by_len.setdefault(L, []).append(y)
        lines += [f"## {path} ({len(runs)} repetições, {failed} requisições com falha)", "",
                  f"- `TTFT_iso(L) = {ta * 1000:.1f} ms + {tb * 1e6:.2f} µs·L`; erro relativo fora da amostra: mediana "
                  f"{e_tt[0]:.1%}, p90 {e_tt[1]:.1%}",
                  f"- `p̂(N) = {pa * 1000:.1f} ms + {pb * 1e6:.2f} µs·N` (N = tokens de prompt no lote); erro relativo fora "
                  f"da amostra: mediana {e_pre[0]:.1%}, p90 {e_pre[1]:.1%}",
                  f"- `TPOT_iso` = {np.median(tpot1) * 1000:.2f} ms com 1 fluxo (CV entre repetições "
                  f"{ref[path]['tpot_iso_cv_between_reps'] or float('nan'):.1%}), {np.median(tpot8) * 1000:.2f} ms com 8", "",
                  "| L (tokens) | n | TTFT mediano (ms) | ajuste (ms) |", "| --- | --- | --- | --- |"]
        for L in sorted(by_len):
            lines.append(f"| {L} | {len(by_len[L])} | {np.median(by_len[L]) * 1000:.1f} | {(ta + tb * L) * 1000:.1f} |")
        lines.append("")
    json.dump(ref, open(os.path.join(dest, "latencia_ref.json"), "w"), indent=1)
    open(os.path.join(dest, "iso_fit.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
