"""Per-level performance indicators of every downloaded harness job, to characterize the shared node's speed over time.

Usage: python3 polyaxon/cluster_history.py <downloads dir> <jobs.json> <out.csv>

<downloads dir> holds one folder per job (`polyaxon ops artifacts ... --path <dir>/<name>-<uuid8>`, with or without
the outputs/ level of the archive); <jobs.json> is
the `polyaxon ops ls -o json` results list (start/end time and user of every run in the project, used to count the
runs active at the same time). For each level (a folder with requests.json and server_file.log) writes one row:
  job, uuid8, config, step, level, t_start_utc, t_end_utc (first/last worker log line; the container clock is UTC-7)
  slo_pct / ttft_p90_s   SLO S1 (TTFT < 1 s and TPOT < 100 ms, over all requests sent) and TTFT p90
  kvc_driver_err / model_service_crash / dead_workers   failure signals (server.log, GPU scheduler log)
  tpot_med_ms            median time per output token over the level's requests (requests.json)
  step_b1_ms             median decode step time of a worker with one running request ("Decode batch" lines:
                         #running-req / gen throughput); includes sharing the GPU with the other workers of the job
  act_med_s / act_max_s  activation time ("Scheduler activated. Activation takes")
  copy_med_s             model service weight copy, CPU -> GPU, 16 GB ("Time taken to copy model to GPU")
  kvc_init_s             kvcached start-up check of the level (health.log, last attempt), seconds
  health_failed          start-up checks that failed before the level started
  concurrent_runs / concurrent_runs_other_users   project runs "running" in Polyaxon at the level's midpoint (all /
                         other users; Polyaxon's start time includes waiting for a GPU, so this overcounts)
  gpu_bus                PCI bus id of the job's GPU (environment.txt)
  prism_jobs_on_node     downloaded Prism jobs whose container was running at the level's midpoint (this one included)
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys

LOG_TZ = dt.timedelta(hours=7)  # container logs are in UTC-7 (PDT)
TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)")


def parse_ts(s):
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in s else "%Y-%m-%d %H:%M:%S"
    return (dt.datetime.strptime(s, fmt) + LOG_TZ).replace(tzinfo=dt.timezone.utc)


def med(v):
    return round(st.median(v), 4) if v else ""


def level_row(level, jobs):
    r = {}
    reqs = json.load(open(os.path.join(level, "requests.json")))
    r["tpot_med_ms"] = med([q["tpot"] * 1000 for q in reqs if q.get("tpot")])
    ok = [q for q in reqs if q.get("ttft") is not None]
    r["slo_pct"] = round(100 * sum(1 for q in ok if q["ttft"] < 1 and (q.get("tpot") or 0) < 0.1) / len(reqs), 2) if reqs else ""
    tt = sorted(q["ttft"] for q in ok)
    r["ttft_p90_s"] = round(tt[int(0.9 * (len(tt) - 1))], 3) if tt else ""
    sl = os.path.join(level, "server.log")
    txt = open(sl, errors="replace").read() if os.path.exists(sl) else ""
    r["kvc_driver_err"] = len(re.findall(r"cuMem(SetAccess|Create|Map)\(", txt))
    r["model_service_crash"] = txt.count("in run_model_service")
    gs = os.path.join(level, "server_file.log.gpu_scheduler.log")
    r["dead_workers"] = open(gs, errors="replace").read().count(" died (serving") if os.path.exists(gs) else ""
    first = last = None
    steps, acts = [], []
    log = os.path.join(level, "server_file.log")
    if os.path.exists(log):
        for line in open(log, errors="replace"):
            m = TS.match(line)
            if not m or "GPU=0 Worker" not in line:
                continue
            t = parse_ts(m[1])
            first = first or t
            last = t
            if "Decode batch" in line:
                b = re.search(r"#running-req: (\d+)", line)
                g = re.search(r"gen throughput \(token/s\): ([0-9.]+)", line)
                if b and g and int(b[1]) == 1 and float(g[1]) > 0:
                    steps.append(1000 / float(g[1]))
            a = re.search(r"Activation takes ([0-9.]+)", line)
            if a:
                acts.append(float(a[1]))
    r["t_start_utc"] = first.isoformat() if first else ""
    r["t_end_utc"] = last.isoformat() if last else ""
    r["step_b1_ms"] = med(steps)
    r["n_step_b1"] = len(steps)
    r["act_med_s"] = med(acts)
    r["act_max_s"] = round(max(acts), 2) if acts else ""
    copies = []
    ms = os.path.join(level, "server_file.log.model_service.log")
    if os.path.exists(ms):
        copies = [float(x) for x in re.findall(r"Time taken to copy model to GPU [^:]*: ([0-9.]+)", open(ms, errors="replace").read())]
    r["copy_med_s"] = med(copies)
    hl = os.path.join(level, "health.log")
    r["kvc_init_s"], r["health_failed"] = "", ""
    if os.path.exists(hl):
        txt = open(hl, errors="replace").read()
        inits = re.findall(r"health: (\d+)/(\d+) processes initialized kvcached \([^)]*\) in ([0-9.]+) s", txt)
        if inits:
            r["kvc_init_s"] = float(inits[-1][2])
        r["health_failed"] = txt.count("== unhealthy")
    r["gpu_bus"] = ""
    for env in (os.path.join(level, "..", "..", "environment.txt"), os.path.join(level, "..", "..", "..", "environment.txt")):
        if os.path.exists(env):
            m = re.search(r"^(0000[0-9A-Fa-f:.]+),", open(env, errors="replace").read(), re.M)
            r["gpu_bus"] = m[1] if m else ""
            break
    if first and last:
        mid = first + (last - first) / 2
        act = [j for j in jobs if j["start"] and j["start"] <= mid <= (j["end"] or mid)]
        r["concurrent_runs"] = len(act)
        r["concurrent_runs_other_users"] = len([j for j in act if j["user"] != jobs_owner])
    return r


def main():
    global jobs_owner
    root, jobs_json, out = sys.argv[1:4]
    raw = json.load(open(jobs_json))
    jobs = []
    for j in raw:
        f = lambda k: dt.datetime.fromisoformat(j[k]).astimezone(dt.timezone.utc) if j.get(k) else None
        jobs.append({"start": f("started_at"), "end": f("finished_at"), "user": j.get("user"), "name": j.get("name")})
    owners = [j["user"] for j in raw if (j.get("name") or "").startswith("prism-examples")]
    jobs_owner = max(set(owners), key=owners.count)
    rows = []
    for req in sorted(glob.glob(os.path.join(root, "*", "**", "requests.json"), recursive=True)):
        level = os.path.dirname(req)
        rel = os.path.relpath(level, root).split(os.sep)
        job = rel[0]
        parts = rel[2:] if rel[1] == "outputs" else rel[1:]  # [outputs/]<config>/<step>/<level> or [outputs/]<step>/<level>
        cfg, step, lvl = (parts[0], parts[1], parts[2]) if len(parts) >= 3 else ("", parts[0], parts[-1])
        try:
            r = level_row(level, jobs)
        except Exception as e:
            print(f"skip {level}: {e}", file=sys.stderr)
            continue
        rows.append({"job": job.rsplit("-", 1)[0], "uuid8": job.rsplit("-", 1)[1], "config": cfg, "step": step,
                     "level": lvl, **r})
    # Prism jobs running on the node at each level's midpoint: a job's container runs from its first
    # environment.txt (container start) to its last level's end; only jobs in <downloads dir> are counted
    spans = {}
    for r in rows:
        if not r["t_start_utc"]:
            continue
        s0, e0 = spans.get(r["uuid8"], (None, None))
        e1 = r["t_end_utc"]
        spans[r["uuid8"]] = (s0, max(e0, e1) if e0 else e1)
    for jd in glob.glob(os.path.join(root, "*")):
        u = jd.rsplit("-", 1)[-1]
        if u not in spans:
            continue
        ts = []
        for env in glob.glob(os.path.join(jd, "**", "environment.txt"), recursive=True):
            m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", open(env, errors="replace").read())
            if m:
                ts.append(m[1].replace("Z", "+00:00"))
        spans[u] = (min(ts) if ts else None, spans[u][1])
    for r in rows:
        if not r["t_start_utc"]:
            continue
        a, b = dt.datetime.fromisoformat(r["t_start_utc"]), dt.datetime.fromisoformat(r["t_end_utc"])
        mid = a + (b - a) / 2
        r["prism_jobs_on_node"] = sum(1 for s0, e0 in spans.values()
                                      if s0 and dt.datetime.fromisoformat(s0) <= mid <= dt.datetime.fromisoformat(e0))
    keys = ["job", "uuid8", "config", "step", "level", "t_start_utc", "t_end_utc", "slo_pct", "ttft_p90_s", "tpot_med_ms", "step_b1_ms",
            "n_step_b1", "act_med_s", "act_max_s", "copy_med_s", "kvc_init_s", "health_failed", "concurrent_runs",
            "concurrent_runs_other_users", "gpu_bus", "kvc_driver_err", "model_service_crash", "dead_workers", "prism_jobs_on_node"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} levels -> {out}")


if __name__ == "__main__":
    main()
