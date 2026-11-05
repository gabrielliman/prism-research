"""Extract compact data from the ovl_* overload steps (run_examples.sh) for plotting.

Usage: python3 polyaxon/extract_ovl.py <outputs dir> <dest dir> [--step-name NAME]

For each level <outputs>/<step>/rate<r>/ (ts<s>/ for ovl_trace) writes <dest>/<NAME or step>/<level>/:
  summary.json  overload_load.py summary (as is)
  requests.csv  one row per request (arrival, status, TTFT, TPOT, latency, ...; times from load start)
  gpu.csv       nvidia-smi samples: t, used_gb, total_gb, util
  events.csv    t, source, kind, model, value; from the logs:
                  controller   activate (ACTION), evict (idle eviction), evict_pressure / evict_fair
                               evict_swap / evict_edf / evict_lvf (PRISM_EVICTION strategies; value = the waiting model it made room for),
                               no_fit (No suitable GPU found),
                               free_mem (free GPU memory the controller saw, GB)
                  gpu_sched    act_req / act_ok / deact_ok (activation requests and completions),
                               model_lost (failed activation or dead worker; value = reason),
                               worker_dead (value = worker id),
                               stale_deact (late deactivation ignored: the model was re-activated since; replaces its deact_ok)
                  worker       retract (SGLang "Decode out of memory", value = retracted requests),
                               preempt (running requests retracted at deactivation, value = count),
                               drain (drain before deactivation, value = seconds),
                               kv_refused (Prism's kvcached fix refused KV pages, value = tokens),
                               act_failed (activation rolled back for lack of memory)
                               kv_oom (kvcached cuMemCreate out of memory), oom (torch.OutOfMemoryError),
                               prefill_postponed (prefill KV full: the batch waits instead of crashing),
                               worker_exit (a worker exited after an exception, the others kept running)
and copies configs/<step>.json to <dest>/<NAME or step>/config.json.

Times are seconds from the load start. Since F2.1 the generator records the load start's wall clock
(summary.json load_start_wall), converted to the logs' local clock with utc_offset_h. For older runs the load start
is placed with the GPU scheduler: an active model's request is admitted within ~10 ms of its arrival, so t0 is the
offset that lines up the most of the first 100 arrivals with an "Admitted ... for <model>" line (this can be off by
seconds under compute overload, where admission lags the arrival).
No numpy needed.
"""
import bisect
import csv
import datetime
import glob
import json
import os
import re
import shutil
import sys

TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)")


def parse_ts(s):
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in s else "%Y-%m-%d %H:%M:%S"
    return datetime.datetime.strptime(s, fmt).timestamp()


def log_lines(path):
    """(timestamp, line) for each line; lines without a timestamp get the previous one."""
    if not os.path.exists(path):
        return
    ts = None
    with open(path, errors="replace") as f:
        for line in f:
            m = TS.match(line)
            if m:
                ts = parse_ts(m.group(1))
            if ts is not None:
                yield ts, line


def admitted_within(ts_sorted, t, window):
    i = bisect.bisect_left(ts_sorted, t)
    return i < len(ts_sorted) and ts_sorted[i] - t < window


def utc_offset_h(d):
    """Hours to add to the server logs' wall clock to get UTC. The logs use the container's local time (UTC−7 in
    October 2026, Pacific daylight time; UTC−8 from November) while environment.txt (or, in older jobs, run.log) is
    written in UTC when the suite line starts, a few minutes before its first server log line: the offset is the whole
    hours of that gap, rounded down. None when the job left neither."""
    import math
    cfg_dir = os.path.dirname(os.path.dirname(d))
    first = [next(iter(log_lines(p)), (None,))[0]
             for p in glob.glob(os.path.join(cfg_dir, "ovl_*", "*", "server_file.log.gpu_scheduler.log"))]
    first = [t for t in first if t is not None]
    m = None
    for name, rx in (("environment.txt", r"(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)Z"),
                     ("run.log", r"^start (\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)Z")):
        p = os.path.join(cfg_dir, name)
        if os.path.exists(p) and (m := re.search(rx, open(p, errors="replace").read(), re.M)):
            break
    if not m or not first:
        return None
    return -math.floor((min(first) - parse_ts(f"{m.group(1)} {m.group(2)}")) / 3600 + 1e-6)


def load_start(level_dir, requests):
    """Load start on the logs' clock: the generator's wall-clock start (summary.json load_start_wall, from F2.1)
    shifted by utc_offset_h; for older runs, load_start_heuristic."""
    summ = os.path.join(level_dir, "summary.json")
    lsw = json.load(open(summ)).get("load_start_wall") if os.path.exists(summ) else None
    off = utc_offset_h(level_dir) if lsw is not None else None
    if lsw is not None and off is not None:
        return lsw - 3600 * off
    return load_start_heuristic(level_dir, requests)


def load_start_heuristic(level_dir, requests):
    admits = {}  # model -> admission timestamps
    for ts, line in log_lines(os.path.join(level_dir, "server_file.log.gpu_scheduler.log")):
        if m := re.search(r"Admitted \d+ requests for (\S+)", line):
            admits.setdefault(m.group(1), []).append(ts)
    first = sorted(requests, key=lambda r: r["arrival"])[:100]
    # Candidates pair early arrivals with admissions of the same model; the server's warm-up requests
    # are admitted too, so keep the candidate that lines up the most arrivals with an admission.
    best, best_score = None, -1
    for r in first[:20]:
        for ts in admits.get(r["model"], [])[:200]:
            t0 = ts - r["arrival"]
            score = sum(admitted_within(admits.get(q["model"], []), t0 + q["arrival"], 0.1) for q in first)
            if score > best_score:
                best, best_score = t0, score
    return best


def events(level_dir, t0):
    rows = []
    for ts, line in log_lines(os.path.join(level_dir, "server_file.log.global_controller.log")):
        t = round(ts - t0, 3)
        if m := re.search(r"ACTION: activate inactive model (\S+)", line):
            rows.append((t, "controller", "activate", m.group(1), ""))
        elif m := re.search(r"ACTION: deactivate (\S+?):\d+ .*idle instance eviction", line):
            rows.append((t, "controller", "evict", m.group(1), ""))
        elif m := re.search(r"ACTION: deactivate (\S+?):\d+ .*Reason: (pressure eviction|fair rotation|throughput swap|edf rotation|lvf rotation) for (\S+)", line):
            kind = {"pressure eviction": "evict_pressure", "fair rotation": "evict_fair", "edf rotation": "evict_edf",
                    "lvf rotation": "evict_lvf"}.get(m.group(2), "evict_swap")
            rows.append((t, "controller", kind, m.group(1), m.group(3)))
        elif m := re.search(r"No suitable GPU found for inactive model (\S+)", line):
            rows.append((t, "controller", "no_fit", m.group(1), ""))
        elif m := re.search(r"GPU 0, mem ([0-9.]+)", line):
            rows.append((t, "controller", "free_mem", "", m.group(1)))
    for ts, line in log_lines(os.path.join(level_dir, "server_file.log.gpu_scheduler.log")):
        t = round(ts - t0, 3)
        if m := re.search(r"Received activate request for model (\S+)", line):
            rows.append((t, "gpu_sched", "act_req", m.group(1), ""))
        elif m := re.search(r"Model (\S+) \(instance \d+\) activation succeeded", line):
            rows.append((t, "gpu_sched", "act_ok", m.group(1), ""))
        elif m := re.search(r"Model (\S+) \(instance \d+\) deactivation succeeded", line):
            rows.append((t, "gpu_sched", "deact_ok", m.group(1), ""))
        elif m := re.search(r"Model (\S+) lost on GPU \d+: (.*)", line):
            rows.append((t, "gpu_sched", "model_lost", m.group(1), m.group(2).strip()))
        elif m := re.search(r"Worker (\d+) on GPU \d+ died", line):
            rows.append((t, "gpu_sched", "worker_dead", "", m.group(1)))
        elif m := re.search(r"Ignoring the late deactivation of (\S+?):", line):
            # the "deactivation succeeded" line just before it did not change the model's state
            last = next((i for i in range(len(rows) - 1, -1, -1) if rows[i][2:4] == ("deact_ok", m.group(1))), None)
            if last is not None:
                rows.pop(last)
            rows.append((t, "gpu_sched", "stale_deact", m.group(1), ""))
    # server.log has the kvcached C++ messages; server_file.log has the workers' Python logging.
    for name in ("server_file.log", "server.log"):
        for ts, line in log_lines(os.path.join(level_dir, name)):
            t = round(ts - t0, 3)
            model = m.group(1) if (m := re.search(r"\((model_\d+)\)", line)) else ""
            if m := re.search(r"Decode out of memory happened. #retracted_reqs: (\d+)", line):
                rows.append((t, "worker", "retract", model, m.group(1)))
            elif m := re.search(r"Retract running batch, running batch size: (\d+)", line):
                rows.append((t, "worker", "preempt", model, m.group(1)))
            elif m := re.search(r"Drained for ([0-9.]+) s", line):
                rows.append((t, "worker", "drain", model, m.group(1)))
            elif m := re.search(r"KV allocation of (\d+) tokens refused", line):
                rows.append((t, "worker", "kv_refused", model, m.group(1)))
            elif m := re.search(r"Activation of (\S+) failed", line):
                rows.append((t, "worker", "act_failed", m.group(1), ""))
            elif "Prefill postponed" in line:
                rows.append((t, "worker", "prefill_postponed", model, ""))
            elif "Worker exits after an exception" in line:
                rows.append((t, "worker", "worker_exit", model, ""))
            elif name == "server.log" and "cuMem" in line and "out of memory" in line:
                rows.append((t, "worker", "kv_oom", "", ""))
            elif "torch.OutOfMemoryError" in line:
                rows.append((t, "worker", "oom", model, ""))
    return sorted(rows)


def gpu_rows(path, t0):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) < 4 or not row[1].strip().isdigit():
                continue
            ts = datetime.datetime.strptime(row[0].strip(), "%Y/%m/%d %H:%M:%S.%f").timestamp()
            rows.append((round(ts - t0, 3), round(float(row[1]) / 1024, 3), round(float(row[2]) / 1024, 3),
                         float(row[3])))
    return rows


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def extract_level(d, lvl):
    """One level directory of the run outputs -> lvl (summary.json, requests.csv, gpu.csv, events.csv)."""
    os.makedirs(lvl, exist_ok=True)
    shutil.copy(os.path.join(d, "summary.json"), lvl)
    reqs = json.load(open(os.path.join(d, "requests.json")))
    cols = ["id", "model", "arrival", "prompt_len", "output_len", "status", "ttft", "tpot", "latency",
            "generated", "error", "slo_class"]
    write_csv(os.path.join(lvl, "requests.csv"), cols,
              [[(r.get(c) or "")[:120] if c == "error" else r.get(c, "") for c in cols] for r in reqs])
    t0 = load_start(d, reqs)
    write_csv(os.path.join(lvl, "gpu.csv"), ["t", "used_gb", "total_gb", "util"],
              gpu_rows(os.path.join(d, "gpu.csv"), t0))
    ev = events(d, t0)
    write_csv(os.path.join(lvl, "events.csv"), ["t", "source", "kind", "model", "value"], ev)
    print(f"{lvl}: {len(reqs)} requests, {len(ev)} events")


def main():
    args = sys.argv[1:]
    name = None
    if "--step-name" in args:
        i = args.index("--step-name")
        name = args[i + 1]
        del args[i:i + 2]
    out, dest = args
    for step_dir in sorted(glob.glob(os.path.join(out, "ovl_*"))):
        step = os.path.basename(step_dir)
        step_dest = os.path.join(dest, name or step)
        os.makedirs(step_dest, exist_ok=True)
        cfg = os.path.join(out, "configs", f"{step}.json")
        if os.path.exists(cfg):
            shutil.copy(cfg, os.path.join(step_dest, "config.json"))
        for d in sorted(glob.glob(os.path.join(step_dir, "rate*")) + glob.glob(os.path.join(step_dir, "ts*"))):
            if not os.path.exists(os.path.join(d, "summary.json")):
                print(f"skip {d}: no summary.json")
                continue
            extract_level(d, os.path.join(step_dest, os.path.basename(d)))


if __name__ == "__main__":
    main()
