#!/usr/bin/env python3
"""F4.4 campaign driver: submits the queued jobs keeping at most MAX_ACTIVE Prism jobs on the node (counting every
session's `prism-examples-*` runs, CLAUDE.md rule 2), downloads each finished job ONE AT A TIME (rule 4), checks the
pod uuid in run.log, and runs validate_run.py on it. Resumable: the state is the TSV below.

Usage: f4_driver.py [--dry]      (run from the repo root)
State: reports/data/F04/campanha_jobs.tsv   suffix  suite  uuid  submitted_utc  status  downloaded
"""
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

PLX = "/mnt/scratch/scheduler/polyax-env/bin/polyaxon"
PROJ = "kunumi/hpc4ai"
RAW = os.environ.get("F4_RAW", "/mnt/scratch/scheduler/prism-raw/F4")
STATE = os.environ.get("F4_STATE", "reports/data/F04/campanha_jobs.tsv")
QUEUE = os.environ.get("F4_QUEUE")  # optional TSV "suffix<TAB>suite" (e.g. the headroom check, D37); default: F4.4
VAL = os.environ.get("F4_VAL", "reports/data/F04/validador")
MAX_ACTIVE = int(os.environ.get("F4_MAX_ACTIVE", 3))  # CLAUDE.md rule 2; >3 only for the D39 concurrency test
TIMEOUT = int(os.environ.get("F4_TIMEOUT", 10800))  # 4 levels of up to ~25 min plus start-ups
# D47: node-wide budget of kvcached workers (one per model, summed over the active Prism jobs). 3 jobs with 10+14+19 =
# 43 workers hit the kvcached CUDA VMM driver error (K1) in most levels (F5 campaign, 2026-11-07); F4 ran up to ~36
# clean. 0 = off (job count only). Prism jobs of other sessions count as UNKNOWN_WORKERS each.
MAX_WORKERS = int(os.environ.get("F4_MAX_WORKERS", 0))
UNKNOWN_WORKERS = 12
STEP_WORKERS = {"ovl_mem": 10, "ovl_phases": 10, "ovl_kv": 4, "ovl_compute": 2, "ovl_trace": 8, "ovl_trace_big": 12,
                "ovl_mix": 10, "ovl_zipf": 10, "ovl_bursty": 10, "ovl_diurnal": 10, "ovl_classes": 10,
                "ovl_sizes": 8}  # run_examples.sh defaults (ovl_mix 8 + 2; ovl_sizes 2+3+2+1); ovl_tr_* 12
FINAL = {"succeeded", "failed", "stopped", "upstream_failed", "skipped", "done"}
PLAN = ["C3", "C1n8", "C1n14", "C2", "T1"]  # 5 reps (PLANO_AGENTE F4.4)
D29 = ["C6", "C7", "C8", "T3", "C10"]  # 2 reps (D29 item 4, Gabriel's scope 2026-11-05)


def queue():
    if QUEUE:
        return [tuple(l.rstrip("\n").split("\t")[:2]) for l in open(QUEUE) if l.strip() and not l.startswith("#")]
    q = []
    for rep in range(1, 6):
        order = "a" if rep % 2 else "b"
        for w in PLAN + (D29 if rep <= 2 else []):
            q.append((f"f4-{w.lower()}-{rep}", f"polyaxon/configs/f4_camp_{w}_{order}_suite.tsv"))
    return q


def suite_workers(suite):
    """Largest number of kvcached workers (models) of any line of a suite: PRISM_OVL_N (+ PRISM_OVL_N2 for ovl_mix)
    or the step's default; PRISM_OVL_DEDICATED lines serve one model."""
    most = 0
    for line in open(suite):
        if line.startswith("#") or "\t" not in line:
            continue
        env = dict(kv.split("=", 1) for kv in line.split("\t", 1)[1].split() if "=" in kv)
        step = env.get("PRISM_STEPS", "")
        if "PRISM_OVL_DEDICATED" in env:
            n = 1
        elif "PRISM_OVL_N" in env:
            n = int(env["PRISM_OVL_N"]) + (int(env.get("PRISM_OVL_N2", 2)) if step == "ovl_mix" else 0)
        else:
            n = 12 if step.startswith("ovl_tr_") else STEP_WORKERS.get(step, UNKNOWN_WORKERS)
        most = max(most, n)
    return most


def pick(q, used):
    """Index of the next queued job to submit under the worker budget, or None: strict FIFO, the head goes when it fits
    (a job behind it could only go while leaving room for the head if the head already fits, so skipping ahead would
    starve large jobs and buy nothing)."""
    if not q:
        return None
    return 0 if not MAX_WORKERS or used + suite_workers(q[0][1]) <= MAX_WORKERS else None


def log(msg):
    print(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {msg}", flush=True)


def load_state():
    if not os.path.exists(STATE):
        return {}
    with open(STATE) as f:
        return {r["suffix"]: r for r in csv.DictReader(f, delimiter="\t")}


def save_state(st):
    cols = ["suffix", "suite", "uuid", "submitted_utc", "status", "downloaded"]
    tmp = STATE + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, cols, delimiter="\t")
        w.writeheader()
        for r in st.values():
            w.writerow(r)
    os.replace(tmp, STATE)


def runs():
    out = subprocess.run([PLX, "ops", "ls", "-p", PROJ, "--limit", "60", "-o", "json"], capture_output=True,
                         text=True, timeout=300).stdout
    return json.loads(out[out.index("{"):])["results"]


def submit(suffix, suite):
    env = dict(os.environ, PRISM_JOB_SUFFIX=f"-{suffix}",
               PRISM_JOB_ENV=f"PRISM_SUITE={suite} PRISM_TIMEOUT={TIMEOUT}")
    out = subprocess.run(["polyaxon/submit.sh"], env=env, capture_output=True, text=True, timeout=900)
    m = re.search(r"@([0-9a-f]{32})", out.stdout + out.stderr)
    if not m:
        raise RuntimeError(f"submit {suffix} failed: {out.stdout[-500:]} {out.stderr[-500:]}")
    return m.group(1)


def download(r):
    dest = os.path.join(RAW, r["suffix"])
    os.makedirs(dest, exist_ok=True)
    subprocess.run([PLX, "ops", "artifacts", "-p", PROJ, "-uid", r["uuid"], "-d", "outputs", "--path", dest],
                   capture_output=True, text=True, timeout=3600, check=True)
    runlog = os.path.join(dest, "outputs", "run.log")
    hosts = set(re.findall(r"host: plx-operation-([0-9a-f]{32})", open(runlog, errors="replace").read()))
    if hosts != {r["uuid"]}:
        raise RuntimeError(f"{r['suffix']}: run.log pods {hosts} != {r['uuid']} (mixed artifacts?)")
    os.makedirs(VAL, exist_ok=True)
    v = subprocess.run(["python3", "polyaxon/validate_run.py", "--csv", os.path.join(VAL, f"{r['suffix']}.csv"), dest],
                       capture_output=True, text=True, timeout=1800)
    log(f"{r['suffix']}: {v.stdout.strip().splitlines()[-1] if v.stdout.strip() else v.stderr[-300:]}")


def main():
    dry = "--dry" in sys.argv
    st = load_state()
    q = [x for x in queue() if x[0] not in st]
    log(f"{len(st)} jobs in state, {len(q)} to submit")
    if dry:
        for x in q:
            print(*x)
        return
    while True:
        rs = runs()
        by_uuid = {x["uuid"]: x for x in rs}
        for r in st.values():
            if r["uuid"] in by_uuid:
                r["status"] = by_uuid[r["uuid"]]["status"]
        save_state(st)
        # finished: download sequentially (never in parallel)
        for r in st.values():
            if r["status"] in FINAL and r["downloaded"] != "1":
                try:
                    download(r)
                    r["downloaded"] = "1"
                except Exception as e:  # noqa: BLE001 (keep driving; retry next round)
                    log(f"download {r['suffix']} failed: {e}")
                    r["downloaded"] = "err"
                save_state(st)
        active = {x["uuid"] for x in rs if x["name"].startswith("prism-examples") and x["status"] not in FINAL}
        active |= {r["uuid"] for r in st.values() if r["status"] not in FINAL}
        mine = {r["uuid"]: r["suite"] for r in st.values()}
        used = sum(suite_workers(mine[u]) if u in mine else UNKNOWN_WORKERS for u in active)
        while q and len(active) < MAX_ACTIVE:
            i = pick(q, used)
            if i is None:
                break
            suffix, suite = q.pop(i)
            used += suite_workers(suite)
            uid = submit(suffix, suite)
            st[suffix] = {"suffix": suffix, "suite": suite, "uuid": uid,
                          "submitted_utc": f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}", "status": "created",
                          "downloaded": "0"}
            save_state(st)
            active.add(uid)
            log(f"submitted {suffix} {uid[:8]} ({len(active)} active, {used} workers)")
            time.sleep(20)
        if not q and all(r["status"] in FINAL and r["downloaded"] == "1" for r in st.values()):
            log("campaign done")
            return
        time.sleep(180)


if __name__ == "__main__":
    main()
