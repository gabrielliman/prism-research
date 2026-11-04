"""Overhead of the controller decision log (F2.8): throughput and controller cycle time with and without it.

Usage: python3 polyaxon/overhead.py <dest.md> <outputs dir> [...]
       each outputs dir is a downloaded job (<job>/outputs/<suite line>/<step>/<level>/), suite lines named *_on* /
       *_off* (f2_overhead_suite.tsv, f2_smoke_suite.tsv), in the order they ran.

Per level: output tokens/s and served req/s (summary.json), the policy's time per cycle ("Total time for global
scheduling" in the controller log: gen_actions, where the log is written) and the decision log's size. Throughput
is compared with a least-squares fit tok/s = a + b·(position in the job) + c·[log on], because the node got faster
during the job and the arms alternate on/off (so "off" always ran after "on"); c is the overhead estimate, with a
95% interval from the residuals. Needs numpy (/mnt/scratch/scheduler/opt-env/bin/python).
"""
import glob
import json
import os
import re
import sys

import numpy as np

CYCLE = re.compile(r"Total time for global scheduling: ([0-9.]+)s")


def main():
    dest, roots = sys.argv[1], sys.argv[2:]
    lines = ["# Sobrecusto do log de decisões (gerado por `polyaxon/overhead.py`)", "",
             "| job | linha | log | tok/s de saída | req/s atendidas | ciclos | tempo do ciclo, média / p99 (ms) | log (KB) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    fit = []
    for root in roots:
        lvls = []
        for s in glob.glob(os.path.join(root, "*", "ovl_*", "*", "summary.json")):
            d = os.path.dirname(s)
            line = d.split(os.sep)[-3]
            # order in the job: the suite line's start in its run.log (file times are reset by the download)
            m = re.search(r"^start (\S+)Z", open(os.path.join(os.path.dirname(os.path.dirname(d)), "run.log"),
                                               errors="replace").read(), re.M)
            start = m.group(1) if m else line
            lvls.append((start, line, d))
        lvls.sort()
        job = os.path.basename(os.path.dirname(root.rstrip("/")))
        for pos, (_, line, d) in enumerate(lvls):
            s = json.load(open(os.path.join(d, "summary.json")))
            on = "_on" in line
            cyc = [float(m.group(1)) * 1000 for m in map(CYCLE.search,
                   open(os.path.join(d, "server_file.log.global_controller.log"), errors="replace")) if m]
            dl = os.path.join(d, "decisions.jsonl")
            kb = os.path.getsize(dl) / 1024 if os.path.exists(dl) else 0
            lines.append(f"| {job} | {line} | {'sim' if on else 'não'} | {s['output_tok_s']:.0f} | {s['served_rps']:.2f} | "
                         f"{len(cyc)} | {np.mean(cyc):.2f} / {np.quantile(cyc, 0.99):.2f} | {kb:.0f} |")
            fit.append((job, pos, on, s["output_tok_s"], cyc))
    lines.append("")
    for job in sorted({f[0] for f in fit}):
        rows = [f for f in fit if f[0] == job]
        on_c = np.concatenate([f[4] for f in rows if f[2]])
        off_c = np.concatenate([f[4] for f in rows if not f[2]])
        lines.append(f"**{job}, tempo do ciclo do controlador:** com log {on_c.mean():.2f} ms, sem log {off_c.mean():.2f} ms "
                     f"(diferença {on_c.mean() - off_c.mean():+.2f} ms por ciclo de 5 s = "
                     f"{(on_c.mean() - off_c.mean()) / 5000:+.4%} do tempo).")
        if len(rows) >= 4:
            X = np.column_stack([np.ones(len(rows)), [f[1] for f in rows], [float(f[2]) for f in rows]])
            y = np.array([f[3] for f in rows])
            coef, res, *_ = np.linalg.lstsq(X, y, rcond=None)
            dof = len(rows) - 3
            sigma2 = float(res[0]) / dof if len(res) and dof > 0 else float("nan")
            se = np.sqrt(sigma2 * np.linalg.inv(X.T @ X)[2, 2])
            t = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78}.get(dof, 2.0)
            base = y[[not f[2] for f in rows]].mean()
            lines.append(f"**{job}, vazão:** efeito do log = {coef[2]:+.0f} tok/s ({coef[2] / base:+.1%}), IC 95% "
                         f"[{(coef[2] - t * se) / base:+.1%}, {(coef[2] + t * se) / base:+.1%}]; tendência ao longo do job "
                         f"{coef[1]:+.0f} tok/s por nível.")
        lines.append("")
    open(dest, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
