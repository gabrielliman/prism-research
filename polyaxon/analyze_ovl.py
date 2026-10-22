"""Summarize the ovl_* overload steps (run_examples.sh) from downloaded run outputs.

Usage: python3 polyaxon/analyze_ovl.py <outputs dir> [<outputs dir> ...]

For each level (<outputs>/<step>/rate<r>/) prints the load side (overload_load.py summary.json),
the GPU side (gpu.csv: nvidia-smi every second) and the controller side (global controller log):
  offered/served req/s, ok/failed/unserved, TTFT, TPOT, SLO attainment;
  peak GPU memory used, share of samples with the GPU >= 95% busy;
  activations, idle evictions, "No suitable GPU found" warnings (a model with requests that does
  not fit), lowest free memory the controller saw.
No numpy needed.
"""
import csv
import glob
import json
import os
import re
import sys


def gpu_stats(path):
    if not os.path.exists(path):
        return None
    used, util, total = [], [], None
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) < 4 or not row[1].strip().replace(".", "").isdigit():
                continue
            used.append(float(row[1])); total = float(row[2]); util.append(float(row[3]))
    if not used:
        return None
    return {"peak_used_gb": max(used) / 1024, "total_gb": total / 1024,
            "busy95": sum(u >= 95 for u in util) / len(util), "samples": len(used)}


def controller_stats(level_dir):
    log = os.path.join(level_dir, "server_file.log.global_controller.log")
    if not os.path.exists(log):
        return None
    t = open(log, errors="replace").read()
    free = [float(x) for x in re.findall(r"GPU 0, mem ([0-9.]+)", t)]
    return {"activations": len(re.findall(r"ACTION: activate inactive model", t)),
            "evictions": len(re.findall(r"Reason: idle instance eviction", t)),
            "no_fit": len(re.findall(r"No suitable GPU found for inactive model", t)),
            "no_fit_models": sorted(set(re.findall(r"No suitable GPU found for inactive model (\S+)", t)),
                                    key=lambda m: int(m.split("_")[-1])),
            "min_free_gb": min(free) if free else None}


def pct(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def main():
    for out in sys.argv[1:]:
        for step_dir in sorted(glob.glob(os.path.join(out, "ovl_*"))):
            print(f"\n=== {os.path.basename(step_dir)}  ({out})")
            print("rate/model | offered | served | ok | failed | unserved | TTFT p50/p99 | TPOT mean | SLO | "
                  "GPU peak used | GPU >=95% busy | activ/evict/no-fit | min free")
            levels = sorted(glob.glob(os.path.join(step_dir, "rate*")) + glob.glob(os.path.join(step_dir, "ts*")),
                            key=lambda d: float(re.sub(r"^(rate|ts)", "", os.path.basename(d))))
            for d in levels:
                rate = os.path.basename(d)
                sp = os.path.join(d, "summary.json")
                g, c = gpu_stats(os.path.join(d, "gpu.csv")), controller_stats(d)
                if not os.path.exists(sp):
                    print(f"{rate} | no summary (server or load failed; see {d}/load.log, server.log)")
                    continue
                s = json.load(open(sp))
                print(" | ".join([
                    rate, f"{s['offered_rps']:.2f}", f"{s['served_rps']:.2f}", str(s["ok"]), str(s["failed"]),
                    str(s["unserved"]), f"{s['ttft_p50'] * 1000:.0f}/{s['ttft_p99'] * 1000:.0f} ms",
                    f"{s['tpot_mean'] * 1000:.1f} ms", pct(s["slo_attainment"]),
                    f"{g['peak_used_gb']:.1f}/{g['total_gb']:.0f} GB" if g else "-",
                    pct(g["busy95"]) if g else "-",
                    f"{c['activations']}/{c['evictions']}/{c['no_fit']}" if c else "-",
                    f"{c['min_free_gb']:.1f} GB" if c and c["min_free_gb"] is not None else "-"]))
                starved = [m for m, v in s["per_model"].items() if v["unserved"] or v["ok"] == 0]
                if starved:
                    print("    models with unserved requests: " + ", ".join(
                        f"{m} (ok {s['per_model'][m]['ok']}/{s['per_model'][m]['sent']}, first ok at "
                        f"{s['per_model'][m]['first_ok_arrival']})" for m in starved))
                if c and c["no_fit_models"]:
                    print(f"    did not fit (controller): {', '.join(c['no_fit_models'])}")


if __name__ == "__main__":
    main()
