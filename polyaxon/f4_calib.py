#!/usr/bin/env python3
"""F4 calibration from existing decision logs (decisions.jsonl, F2.1): no new runs.

For each level it reports
  stall_max_s   longest stretch of consecutive controller cycles in which some ACTIVE model has waiting requests,
                no activation is pending, and no ACTIVE model finished a request (min since_last_finish_s grows).
                This is what the A1.2 detector watches (with tokens instead of finishes, which only makes the
                live signal faster); levels without impasse bound how long a normal pause lasts -> Δ_imp.
  run_p50/p90   running requests per ACTIVE model in cycles where it also has waiting requests (saturated batch):
                the lot a resident model actually serves under load -> b of A1.1.
  free_min_gb   lowest free GPU memory seen by the controller, and free_p10_gb.
The T1 frozen time of each level comes from the validator CSVs (reports/data/*/validador/*.csv).

Usage: f4_calib.py <raw root> [...] [--out tsv]
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd


def level_stats(path):
    stall, best, prev_t = 0.0, 0.0, None
    runs, free = [], []
    for line in open(path):
        try:
            c = json.loads(line)
        except ValueError:
            continue
        t = c["t"]
        g = c["gpus"].get("0", {})
        if g.get("free_gb") is not None:
            free.append(g["free_gb"])
        act = {m: v for m, v in c["models"].items() if v["state"] == "ACTIVE"}
        busy = [m for m, v in act.items() if v["waiting"] > 0]
        pending = bool(g.get("pending"))
        fin = [v["since_last_finish_s"] for v in act.values() if v["since_last_finish_s"] is not None]
        for m in busy:
            if act[m]["running"] is not None:
                runs.append(act[m]["running"])
        if busy and not pending and fin:
            s = min(fin)
            # a stall is "no active model finished since s seconds"; it is reset by any finish
            stall = s
            best = max(best, stall)
        prev_t = t
    r = np.array(runs) if runs else np.array([np.nan])
    f = np.array(free) if free else np.array([np.nan])
    return {"stall_max_s": round(best, 1), "run_p50": float(np.nanpercentile(r, 50)),
            "run_p90": float(np.nanpercentile(r, 90)), "free_min_gb": round(float(np.nanmin(f)), 1),
            "free_p10_gb": round(float(np.nanpercentile(f, 10)), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    val = pd.concat([pd.read_csv(f) for f in glob.glob("reports/data/*/validador/*.csv")])
    t1 = {os.path.join(r, l): s for r, l, s in zip(val.root, val.level, val.t1_frozen_s)}
    status = {os.path.join(r, l): s for r, l, s in zip(val.root, val.level, val.status)}
    rows = []
    for root in a.roots:
        for p in sorted(glob.glob(os.path.join(root, "**", "decisions.jsonl"), recursive=True)):
            d = os.path.dirname(p)
            key = next((k for k in t1 if os.path.normpath(k) == os.path.normpath(d)), None)
            row = {"level": d.replace("/mnt/scratch/scheduler/prism-raw/", ""),
                   "t1_frozen_s": t1.get(key), "status": status.get(key)}
            row.update(level_stats(p))
            rows.append(row)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_colwidth", 70)
    print(df.to_string(index=False))
    if a.out:
        df.to_csv(a.out, sep="\t", index=False)


if __name__ == "__main__":
    sys.exit(main())
