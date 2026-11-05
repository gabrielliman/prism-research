"""F3 dry run: why do the Azure-length workloads leave ~80% unserved? Per level: frozen time, service timeline,
GPU utilization, swaps, retractions/KV errors in the server logs, and served vs prompt length."""
import csv
import glob
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, "polyaxon")
import extract_ovl as ex  # noqa: E402

R = "/mnt/scratch/scheduler/prism-raw/F3-dry"
V = {}
for f in glob.glob("reports/data/F03/validador/dry_*.csv"):
    for r in csv.DictReader(open(f)):
        V[r["level"]] = r
for d in sorted(glob.glob(f"{R}/dry-*/outputs/*/ovl_*/*")):
    if not os.path.exists(f"{d}/requests.json"):
        continue
    rel = d.split("/dry-")[1][2:]
    reqs = json.load(open(f"{d}/requests.json"))
    s = json.load(open(f"{d}/summary.json"))
    dur = s["args"]["duration"]
    ok = [r for r in reqs if r["status"] == "ok"]
    fin = sorted((r["arrival"] + r["latency"]) for r in ok)
    # completions per 60 s bin, over window + drain
    bins = np.histogram(fin, bins=np.arange(0, dur + 360, 60))[0]
    pl_ok = np.median([r["prompt_len"] for r in ok]) if ok else None
    pl_un = np.median([r["prompt_len"] for r in reqs if r["status"] != "ok"]) if len(ok) < len(reqs) else None
    out_tok = sum(r["generated"] for r in ok)
    t0 = ex.load_start(d, reqs)
    gpu = ex.gpu_rows(os.path.join(d, "gpu.csv"), t0)
    util = np.mean([g[3] for g in gpu if 0 <= g[0] <= dur + 300]) if gpu else None
    ev = ex.events(d, t0)
    acts = sum(1 for e in ev if e[2] in ("activate", "activated", "activate_done"))
    kinds = {}
    for e in ev:
        kinds[e[2]] = kinds.get(e[2], 0) + 1
    logtxt = ""
    for lf in glob.glob(f"{d}/server_file.log*"):
        logtxt += open(lf, errors="replace").read()
    pats = {k: len(re.findall(p, logtxt)) for k, p in
            {"retract": r"[Rr]etract", "PrefillKVFull": "PrefillKVFull", "decode_oom": r"[Dd]ecode out of memory|decode OOM",
             "no_fit": "No suitable GPU", "evict": r"[Ee]vict"}.items()}
    v = V.get(rel.split("/", 1)[1] if False else "outputs/" + rel.split("/", 1)[1], {})
    print(f"\n{rel}: served {len(ok)}/{len(reqs)}, out tok {out_tok}, frozen T1 {v.get('t1_frozen_s')} s, GPU util {util and round(util, 1)}%")
    print(f"  completions/min: {list(bins)}")
    print(f"  prompt p50 served {pl_ok}, unserved {pl_un}; events {kinds}")
    print(f"  server log: {pats}")
