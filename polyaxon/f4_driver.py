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
        while q and len(active) < MAX_ACTIVE:
            suffix, suite = q.pop(0)
            uid = submit(suffix, suite)
            st[suffix] = {"suffix": suffix, "suite": suite, "uuid": uid,
                          "submitted_utc": f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}", "status": "created",
                          "downloaded": "0"}
            save_state(st)
            active.add(uid)
            log(f"submitted {suffix} {uid[:8]} ({len(active)} active)")
            time.sleep(20)
        if not q and all(r["status"] in FINAL and r["downloaded"] == "1" for r in st.values()):
            log("campaign done")
            return
        time.sleep(180)


if __name__ == "__main__":
    main()
