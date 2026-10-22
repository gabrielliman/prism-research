"""Extract compact data from the ovl_* overload steps (run_examples.sh) for plotting.

Usage: python3 polyaxon/extract_ovl.py <outputs dir> <dest dir> [--step-name NAME]

For each level <outputs>/<step>/rate<r>/ (ts<s>/ for ovl_trace) writes <dest>/<NAME or step>/<level>/:
  summary.json  overload_load.py summary (as is)
  requests.csv  one row per request (arrival, status, TTFT, TPOT, latency, ...; times from load start)
  gpu.csv       nvidia-smi samples: t, used_gb, total_gb, util
  events.csv    t, source, kind, model, value; from the logs:
                  controller   activate (ACTION), evict (idle eviction), evict_pressure / evict_fair
                               evict_swap (PRISM_EVICTION strategies; value = the waiting model it made room for),
                               no_fit (No suitable GPU found),
                               free_mem (free GPU memory the controller saw, GB)
                  gpu_sched    act_req / act_ok / deact_ok (activation requests and completions)
                  worker       retract (SGLang "Decode out of memory", value = retracted requests),
                               preempt (running requests retracted at deactivation, value = count),
                               drain (drain before deactivation, value = seconds),
                               kv_oom (kvcached cuMemCreate out of memory), oom (torch.OutOfMemoryError)
and copies configs/<step>.json to <dest>/<NAME or step>/config.json.

Times are seconds from the load start. The logs use wall clock, so the load start is placed with the
GPU scheduler: an active model's request is admitted within ~10 ms of its arrival, so t0 is the
offset that lines up the most of the first 100 arrivals with an "Admitted ... for <model>" line.
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


def load_start(level_dir, requests):
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
        elif m := re.search(r"ACTION: deactivate (\S+?):\d+ .*Reason: (pressure eviction|fair rotation|throughput swap) for (\S+)", line):
            kind = {"pressure eviction": "evict_pressure", "fair rotation": "evict_fair"}.get(m.group(2), "evict_swap")
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
            elif name == "server.log" and "cuMemCreate" in line and "out of memory" in line:
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
            lvl = os.path.join(step_dest, os.path.basename(d))
            os.makedirs(lvl, exist_ok=True)
            shutil.copy(os.path.join(d, "summary.json"), lvl)
            reqs = json.load(open(os.path.join(d, "requests.json")))
            cols = ["id", "model", "arrival", "prompt_len", "output_len", "status", "ttft", "tpot", "latency",
                    "generated", "error"]
            write_csv(os.path.join(lvl, "requests.csv"), cols,
                      [[(r.get(c) or "")[:120] if c == "error" else r.get(c, "") for c in cols] for r in reqs])
            t0 = load_start(d, reqs)
            write_csv(os.path.join(lvl, "gpu.csv"), ["t", "used_gb", "total_gb", "util"],
                      gpu_rows(os.path.join(d, "gpu.csv"), t0))
            ev = events(d, t0)
            write_csv(os.path.join(lvl, "events.csv"), ["t", "source", "kind", "model", "value"], ev)
            print(f"{lvl}: {len(reqs)} requests, {len(ev)} events")


if __name__ == "__main__":
    main()
