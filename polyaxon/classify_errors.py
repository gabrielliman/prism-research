"""Count each memory error's signature per level of the load-limit suites (limits_*_suite.tsv).

Usage: python3 polyaxon/classify_errors.py <dest.csv> [--extract <data dir>] <version>:<rep>=<job outputs dir> ...

--extract also writes each level with extract_ovl.extract_level to <data dir>/<suite line>/<version>-r<rep>/<level>/
(plus the level's config.json one directory up), for plot_suite.py timelines.

Each outputs dir is one downloaded job (run.log + <suite line>/<step>/<level>/). One row per level, also for
levels whose server never started (from run.log). Columns (ids as in the report and erros.md):
  start_failed      the server did not start (all attempts), start_k1 kvcached cuMem failures at start-up (F5)
  sent ok unserved failed slo        from summary.json
  failed_conn       requests failed by a connection error: the server went down (S2)
  failed_none_ts    requests failed by the missing finish timestamp (S4)
  k1                kvcached cuMem* out of memory while serving (each one aborts a worker)
  oom_act oom_fwd   torch.OutOfMemoryError while activating (P3/S3) / in a forward pass
  pretty_print      NotImplementedError from tree_cache.pretty_print, KV full in prefill (S1)
  activations       activation requests; act_overlap: requested with another one still loading;
  act_overcommit    requested when the free memory the controller saw, minus the other pending activations
                    (weights + 1 GB each), was below this one's weights + 1 GB (P1)
  act_s_p50 act_s_max  request -> success of an activation (P10)
  frozen_s          longest stretch with the GPU above 100 GB and 0% utilization while requests were still waiting
                    for an answer (T1: every active worker holds its KV and none progresses)
  dead_detected worker_exit act_rollback model_lost stale_ignored prefill_postponed   fixes in action
"""
import csv
import glob
import json
import os
import re
import shutil
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_ovl as ex  # noqa: E402

WEIGHTS_GB = 15.0  # Llama-3.1-8B, all models in these suites
K1 = re.compile(r"cuMem\w+\(.*failed in CUDA driver.*out of memory")
CONN = re.compile(r"connect|ClientOSError", re.I)
COLS = ["version", "rep", "suite", "step", "level", "start_failed", "start_k1", "sent", "ok", "unserved", "failed",
        "slo", "failed_conn", "failed_none_ts", "k1", "oom_act", "oom_fwd", "pretty_print", "activations",
        "act_overlap", "act_overcommit", "act_s_p50", "act_s_max", "frozen_s", "dead_detected", "worker_exit",
        "act_rollback", "model_lost", "stale_ignored", "prefill_postponed"]


def count_lines(paths, rx):
    n = 0
    for p in paths:
        if os.path.exists(p):
            with open(p, errors="replace") as f:
                n += sum(1 for line in f if rx.search(line))
    return n


def ooms(paths):
    """torch OOMs split by where they happened: the traceback above mentions an activation or not."""
    act = fwd = 0
    for p in paths:
        if not os.path.exists(p):
            continue
        prev = deque(maxlen=80)
        with open(p, errors="replace") as f:
            for line in f:
                if "torch.OutOfMemoryError" in line or "torch.cuda.OutOfMemoryError" in line:
                    if any("activate" in x or "load_model" in x or "copy_model" in x for x in prev):
                        act += 1
                    else:
                        fwd += 1
                    prev.clear()
                else:
                    prev.append(line)
    return act, fwd


def activations(ev):
    """P1 and P10 from the controller/GPU scheduler events of one level."""
    free = None
    pending = {}  # model -> request time
    n = overlap = over = 0
    took = []
    for t, src, kind, model, value in sorted(ev, key=lambda e: e[0]):
        if kind == "free_mem":
            free = float(value)
        elif kind == "act_req":
            n += 1
            others = [m for m in pending if m != model]
            overlap += bool(others)
            if free is not None and free - (WEIGHTS_GB + 1) * len(others) < WEIGHTS_GB + 1:
                over += 1
            pending[model] = t
        elif kind == "act_ok" and model in pending:
            took.append(t - pending.pop(model))
        elif kind in ("model_lost", "act_failed"):
            pending.pop(model, None)
    took.sort()
    return n, overlap, over, (took[len(took) // 2] if took else ""), (took[-1] if took else "")


def frozen_s(d, reqs):
    """Longest run of 1 s nvidia-smi samples with > 100 GB used and 0% utilization while a request that would
    end up unserved had already arrived."""
    pending = [x["arrival"] for x in reqs if x["status"] == "unserved"]
    rows = list(ex.gpu_rows(os.path.join(d, "gpu.csv"), ex.load_start(d, reqs)))
    best = run = 0
    for t, used, _, util in rows:
        stuck = pending and t >= min(pending) and float(used) > 100 and float(util) == 0
        run = run + 1 if stuck else 0
        best = max(best, run)
    return best


def start_failures(run_log):
    """(suite line, level) -> start attempts that failed, and levels given up, from the job's run.log."""
    failed, given_up, suite = {}, set(), ""
    if not os.path.exists(run_log):
        return failed, given_up
    for line in open(run_log, errors="replace"):
        if m := re.match(r"=+ suite: (\S+) \(", line):
            suite = m.group(1)
        elif m := re.match(r"\[(ovl_\w+/\S+)\] (start attempt \d+ failed|kvcached failed at start-up)", line):
            failed[(suite, m.group(1))] = failed.get((suite, m.group(1)), 0) + 1
        elif m := re.match(r"\[(ovl_\w+/\S+)\] (NODE UNHEALTHY|.*did not start|.*giving up)", line):
            given_up.add((suite, m.group(1)))
    return failed, given_up


def level_row(d):
    logs = [os.path.join(d, f) for f in ("server.log", "server_file.log")]
    r = {"k1": count_lines(logs, K1),
         "pretty_print": count_lines(logs, re.compile(r"^NotImplementedError\s*$")),
         "start_k1": count_lines(glob.glob(os.path.join(d, "server*.attempt*.log")), K1)}
    r["oom_act"], r["oom_fwd"] = ooms(logs)
    if not os.path.exists(os.path.join(d, "summary.json")):
        r["start_failed"] = 1
        return r
    s = json.load(open(os.path.join(d, "summary.json")))
    reqs = json.load(open(os.path.join(d, "requests.json")))
    r.update(start_failed=0, sent=len(reqs), ok=sum(x["status"] == "ok" for x in reqs),
             unserved=sum(x["status"] == "unserved" for x in reqs),
             failed=sum(x["status"] == "failed" for x in reqs), slo=s.get("slo_attainment", ""),
             failed_conn=sum(x["status"] == "failed" and bool(CONN.search(x.get("error") or "")) for x in reqs),
             failed_none_ts=sum("NoneType" in (x.get("error") or "") for x in reqs))
    r["frozen_s"] = frozen_s(d, reqs)
    ev = ex.events(d, ex.load_start(d, reqs))
    kinds = [e[2] for e in ev]
    (r["activations"], r["act_overlap"], r["act_overcommit"], r["act_s_p50"], r["act_s_max"]) = activations(ev)
    for col, kind in [("dead_detected", "worker_dead"), ("worker_exit", "worker_exit"), ("act_rollback", "act_failed"),
                      ("model_lost", "model_lost"), ("stale_ignored", "stale_deact"),
                      ("prefill_postponed", "prefill_postponed")]:
        r[col] = kinds.count(kind)
    return r


def main():
    dest, jobs, data = sys.argv[1], sys.argv[2:], None
    if jobs[:1] == ["--extract"]:
        data, jobs = jobs[1], jobs[2:]
    rows = []
    for job in jobs:
        tag, out = job.split("=", 1)
        version, rep = tag.split(":")
        failed, given_up = start_failures(os.path.join(out, "run.log"))
        seen = set()
        for d in sorted(glob.glob(os.path.join(out, "*", "ovl_*", "*"))):
            if not os.path.isdir(d):
                continue
            suite, step, level = d.split(os.sep)[-3:]
            seen.add((suite, f"{step}/{level}"))
            row = {"version": version, "rep": rep, "suite": suite, "step": step, "level": level, **level_row(d)}
            row["start_failed"] = int(row["start_failed"] or (suite, f"{step}/{level}") in given_up)
            row["start_k1"] = row["start_k1"] or ""
            rows.append(row)
            if data and not row["start_failed"]:
                run = os.path.join(data, suite, f"{version}-r{rep}")
                ex.extract_level(d, os.path.join(run, level))
                shutil.copy(os.path.join(out, suite, "configs", f"{step}.json"), os.path.join(run, "config.json"))
        for suite, lvl in sorted(set(failed) | given_up):  # levels with no output dir at all
            if (suite, lvl) not in seen:
                step, level = lvl.split("/")
                rows.append({"version": version, "rep": rep, "suite": suite, "step": step, "level": level,
                             "start_failed": 1})
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{dest}: {len(rows)} levels")


if __name__ == "__main__":
    main()
