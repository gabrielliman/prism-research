"""One row per cluster probe (polyaxon/cluster_probe.sh), for the node-variation report.

Usage: python3 polyaxon/cluster_probe_summary.py <probes dir> <out.csv>

<probes dir> holds one folder per probe job (`polyaxon ops artifacts ... --path <dir>/<name>`, archive extracted).
Columns: probe, start_utc, gpu_bus, node load average at start and its max while the probe ran, the median of each
benchmark in probe.json, the local/remote NUMA pinned results (probe_pin_*.json), and from gpu_samples.csv the max SM
clock and the share of samples with a throttle reason other than idle / SW power cap during the benchmarks, and the
kvcached start-up test of 1 and 10 processes (vmm1_ok / vmm1_s, vmm10_ok / vmm10_s).
"""
import csv
import glob
import json
import os
import re
import sys

BENCH = ["cpu_py_loop_s", "launch_us", "matmul_tflops", "hbm_gbs", "h2d_pinned_gbs", "d2h_pinned_gbs",
         "h2d_pageable_gbs", "host_memcpy_gbs", "decode_b1_ms", "decode_b32_ms", "decode_b1_graph_ms"]
IDLE, SW_POWER_CAP = 0x1, 0x4


def main():
    root, out = sys.argv[1:3]
    rows = []
    for pj in sorted(glob.glob(os.path.join(root, "*", "**", "probe.json"), recursive=True)):
        d = os.path.dirname(pj)
        p = json.load(open(pj))
        node = open(os.path.join(d, "node.txt"), errors="replace").read()
        r = {"probe": os.path.relpath(d, root).split(os.sep)[0], "start_utc": p.get("start_utc", "")}
        m = re.search(r"^\d+, GPU-[^,]+, [^,]+, (0000[0-9A-Fa-f:.]+),", node, re.M)
        r["gpu_bus"] = m[1] if m else ""
        m = re.search(r"^loadavg: ([0-9.]+) ([0-9.]+) ([0-9.]+) \d+/(\d+)", node, re.M)
        r["load1_start"], r["threads_node"] = (float(m[1]), int(m[4])) if m else ("", "")
        loads = [float(x) for x in re.findall(r"load=([0-9.]+) ", open(os.path.join(d, "host_samples.log"), errors="replace").read())] \
            if os.path.exists(os.path.join(d, "host_samples.log")) else []
        r["load1_max"] = max(loads) if loads else ""
        for b in BENCH:
            r[b] = round(p[b]["median"], 4) if b in p else ""
        for lab in ("local", "remote"):
            f = os.path.join(d, f"probe_pin_{lab}.json")
            q = json.load(open(f)) if os.path.exists(f) else {}
            for b in ("launch_us", "decode_b1_ms"):
                r[f"{b}_{lab}"] = round(q[b]["median"], 4) if b in q else ""
        for k in (1, 10):
            m = re.search(rf"^vmm_parallel_{k}: health: (\d+)/(\d+) processes initialized kvcached \([^)]*\) in ([0-9.]+) s", node, re.M)
            r[f"vmm{k}_ok"], r[f"vmm{k}_s"] = (f"{m[1]}/{m[2]}", float(m[3])) if m else ("", "")
        clocks, bad, n = [], 0, 0
        gs = os.path.join(d, "gpu_samples.csv")
        if os.path.exists(gs):
            for row in list(csv.reader(open(gs)))[1:]:
                try:
                    util, sm, reason = float(row[1]), float(row[2]), int(row[6], 16)
                except (ValueError, IndexError):
                    continue
                if util < 50:
                    continue
                n += 1
                clocks.append(sm)
                bad += bool(reason & ~(IDLE | SW_POWER_CAP))
        r["sm_clock_max"] = max(clocks) if clocks else ""
        r["sm_clock_med_busy"] = sorted(clocks)[len(clocks) // 2] if clocks else ""
        r["throttle_other_share"] = round(bad / n, 3) if n else ""
        rows.append(r)
    keys = list(rows[0]) if rows else []
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} probes -> {out}")


if __name__ == "__main__":
    main()
