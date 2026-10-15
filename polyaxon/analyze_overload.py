"""Summarize the `overload` step (polyaxon/run_examples.sh) from downloaded run outputs.

Usage: python3 polyaxon/analyze_overload.py <outputs dir> [ttft_slo_scale] [tpot_slo_scale]

For each time-scale level (outputs/overload/ts<x>/) prints completed/aborted requests, throughput,
TTFT/TPOT, and SLO attainment per model and overall. The benchmark's e2e mode with --model-paths
records no SLOs, so per-model SLOs are rebuilt with the repo's own trace generator
(RealWorldTrace.generate_e2e_benchmark_reqs, baseline P95 x scale; benchmark.py defaults to 5).
Units there: slo_ttft in seconds, slo_tpot in ms (outputs record both ttft and tpot in seconds).
Also counts the policy's model activations / idle evictions in the global controller log.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(REPO, "benchmark", "multi-model")
sys.path.insert(0, BENCH)  # benchmark's trace.py shadows the stdlib `trace`, as in benchmark.py
from trace import RealWorldTrace, TraceConfig  # noqa: E402

MODELS = [f"model_{i}" for i in range(1, 9)]


def model_slos(ttft_scale, tpot_scale):
    cfg = TraceConfig(model_paths=MODELS, ttft_slo_scale=ttft_scale, tpot_slo_scale=tpot_scale,
                      slo=100, e2e_benchmark=True, time_scale=1, replication=1)
    reqs = RealWorldTrace(pkl_file_path=os.path.join(BENCH, "real_trace.pkl")) \
        .generate_e2e_benchmark_reqs(cfg, num_models=len(MODELS))
    return {r.model: (r.slo_ttft, r.slo_tpot / 1000.0) for r in reqs}  # both in seconds


def swap_events(level_dir):
    log = os.path.join(level_dir, "server_file.log.global_controller.log")
    if not os.path.exists(log):
        return "-"
    text = open(log, errors="replace").read()
    # simple_global.py gen_actions: "ACTION: activate inactive model ..." / "ACTION: deactivate ...
    # Reason: idle instance eviction" (migrations need >1 GPU).
    act = len(re.findall(r"ACTION: activate inactive model", text))
    deact = len(re.findall(r"ACTION: deactivate \S+ on GPU \d+\. Reason: idle instance eviction", text))
    return f"{act}/{deact}"


def main():
    out = sys.argv[1]
    ttft_scale = float(sys.argv[2]) if len(sys.argv) > 2 else 5
    tpot_scale = float(sys.argv[3]) if len(sys.argv) > 3 else 5
    slos = model_slos(ttft_scale, tpot_scale)
    print(f"SLO (scale ttft x{ttft_scale:g}, tpot x{tpot_scale:g}): " + ", ".join(
        f"{m} {t * 1000:.0f}ms/{p * 1000:.0f}ms" for m, (t, p) in sorted(slos.items())))

    levels = sorted(glob.glob(os.path.join(out, "overload", "ts*")),
                    key=lambda d: -float(os.path.basename(d)[2:]))
    hdr = ("speed", "done", "abort", "req/s", "TTFT mean", "TTFT p99", "TPOT mean", "TPOT p99",
           "SLO ttft", "SLO tpot", "SLO both", "activ/evict")
    print("\n" + " | ".join(hdr))
    per_model_rows = []
    for d in levels:
        ts = float(os.path.basename(d)[2:])
        res = glob.glob(os.path.join(d, "benchmark-results", "*.json"))
        reqs = glob.glob(os.path.join(d, "output-requests", "*.json"))
        if not res or not reqs:
            print(f"{1 / ts:g}x | no results ({d})")
            continue
        r = json.load(open(res[0]))
        outs = json.load(open(reqs[0]))
        ok_ttft, ok_tpot, ok_both = [], [], []
        by_model = defaultdict(list)
        for o in outs:
            t_slo, p_slo = slos[o["model"]]
            a = o["success"] and o["ttft"] < t_slo
            b = o["success"] and o["tpot"] < p_slo
            ok_ttft.append(a); ok_tpot.append(b); ok_both.append(a and b)
            by_model[o["model"]].append(a and b)
        pct = lambda x: f"{100 * np.mean(x):.1f}%"
        print(" | ".join([f"{1 / ts:g}x", str(r.get("completed")), str(r.get("aborted")),
                          f"{r.get('request_throughput', 0):.2f}",
                          f"{r.get('mean_ttft_ms', 0):.0f}ms", f"{r.get('p99_ttft_ms', 0):.0f}ms",
                          f"{r.get('mean_tpot_ms', 0):.1f}ms", f"{r.get('p99_tpot_ms', 0):.1f}ms",
                          pct(ok_ttft), pct(ok_tpot), pct(ok_both), swap_events(d)]))
        per_model_rows.append((f"{1 / ts:g}x", {m: (len(v), np.mean(v)) for m, v in by_model.items()}))

    print("\nSLO attainment (ttft and tpot) per model, n requests in parentheses")
    print("speed | " + " | ".join(MODELS))
    for speed, pm in per_model_rows:
        print(speed + " | " + " | ".join(
            f"{100 * pm[m][1]:.0f}% ({pm[m][0]})" if m in pm else "-" for m in MODELS))


if __name__ == "__main__":
    main()
