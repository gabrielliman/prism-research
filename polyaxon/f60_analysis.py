#!/usr/bin/env python3
"""F6.0 analysis (D49, D50, D51): deadline policies against the F5 baselines, paired by job.

Usage:
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f60_analysis.py <dest dir> <validator.csv> [...]

Every job (polyaxon/f6_0_suites.sh) runs ONE workload with, in the same window (rule 3): the baselines A0.2_A1 and
A0.4, and A2.1 EDF (edf), A9.1 VLT (lvf) and A9.2 residency-aware VLT (lvfr) × {S3 kA=5, S6 kR=1, S6 kR=4} ×
{without (p0), with (p1) preemption}; the deadline arms receive their level's TTFT deadline per request
(PRISM_OVL_SLO_SPEC), the baselines do not depend on it. A job is used only if all its levels are VALIDA (a re-run
replaces it, never mixed).

Outputs in <dest>:
  niveis.csv       per level: attainment at the three F6.0 levels (combined / TTFT-only / TPOT-only) and at
                   S2 kT=10 (post-hoc strict reference) and S1 1 s, TTFT p50/p90/p99, wait tail (D33), rotations,
                   preempted requests, activations/min; for deadline arms the "own" level they were run with
  vs_base.csv      per job and deadline arm: arm − baseline (A0.2_A1 and A0.4) at the arm's own level, three views,
                   TTFT p50/p90, max wait
  preempt.csv      per job, policy and level: p1 − p0 at that level (three views, p50/p90, max wait)
  s3_hipotese.csv  per job and policy: Δ(S3) = p1 − p0 at S3 kA=5, Δ(S6 kR=4), and Δ(S3) − Δ(S6 kR=4) (D49 hypothesis:
                   preemption pays at the tight deadline only), TTFT-only and combined views
  resumo.csv       means over jobs with a 95% bootstrap CI (jobs resampled, 10 000 draws), pooled over workloads and
                   per workload (with 2 repetitions the per-workload CI is a range of 2 values: screening, D50)
"""
import csv
import json
import math
import multiprocessing as mp
import pathlib
import random
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slo_metrics as sm  # noqa: E402
from f5_analysis import extract, events, tail, write_csv  # noqa: E402

LEVELS = {"S3k5": "S3:kA=5,kD=5", "S6k1": "S6:kR=1,kD=5", "S6k2": "S6:kR=2,kD=5", "S6k4": "S6:kR=4,kD=5"}
REFS = {"S2k10": "S2:kT=10,kD=5", "S1": "S1:ttft=1,tpot=0.1"}
BASES = ["A0.2_A1", "A0.4"]
POLICIES = ["edf", "lvf", "lvfr"]
NAMES = {"edf": "A2.1 EDF", "lvf": "A9.1 VLT", "lvfr": "A9.2 VLT residência", "A0.2_A1": "A0.2+A1", "A0.4": "A0.4"}
ORDER = ["C1n10", "T1", "C6n14", "T3"]
VIEWS = ("comb", "so_ttft", "so_tpot")
OTHER = ("ttft_p50", "ttft_p90", "espera_max")


def workload_rep(job):
    m = re.match(r"f6\d*-(\w+?)-(\d+)[a-z]?$", job)
    return {"c1n10": "C1n10", "t1": "T1", "c6n14": "C6n14", "t3": "T3"}[m.group(1)], int(m.group(2))


def parse_config(cfg):
    m = re.match(r"(edf|lvfr|lvfp|lvf|loss|value|pred)_(S3k5|S6k1|S6k2|S6k4)_p([01s])$", cfg)
    # preemption: 0 without, 1 with (global), 2 decided per swap (A9.4, F6.16)
    return (m.group(1), m.group(2), 2 if m.group(3) == "s" else int(m.group(3))) if m else (cfg, None, None)


def level(args):
    v, dest = args
    refs = sm.Refs()
    out, cfg, step, lvl = extract(v, dest)
    job = pathlib.Path(v["root"]).name
    w, rep = workload_rep(job)
    pol, own, pre = parse_config(cfg)
    s = json.load(open(out / "summary.json"))
    reqs, ev, conf = sm.load_level(out)
    sc = sm.ded_scenario(out)
    row = {"job": job, "carga": w, "rep": rep, "config": cfg, "politica": pol, "nivel_proprio": own or "",
           "preempcao": "" if pre is None else pre, "cenário": step, "nível": lvl, "uuid": v["uuid"],
           "enviadas": s["sent"], "atendidas": s["ok"] / s["sent"], "nao_atendidas_n": s["unserved"]}
    for k, spec in {**LEVELS, **REFS}.items():
        m = sm.evaluate(reqs, ev, conf, spec, refs, False, sc)
        row |= {f"{k}_{x}": m[x] for x in VIEWS}
        if k == "S1":
            row |= {x: m[x] for x in ("ttft_p50", "ttft_p90", "ttft_p99")}
    row |= tail(reqs, s["elapsed_s"])
    e = events(out)
    evl = list(csv.DictReader(open(out / "events.csv"))) if (out / "events.csv").exists() else []
    row |= {"rotacoes": sum(x["kind"] in ("evict_edf", "evict_lvf", "evict_loss", "evict_swap") for x in evl),
            "preemptadas": e["preemptadas"], "ativacoes_min": 60 * e["ativacoes"] / (s["elapsed_s"] or 1)}
    for x in VIEWS:  # the arm's own level (deadline arms) for the paired tables
        row[f"proprio_{x}"] = row[f"{own}_{x}"] if own else math.nan
    return row


def boot(vals, n=10000, seed=1):
    vals = [x for x in vals if not (isinstance(x, float) and math.isnan(x))]
    if not vals:
        return math.nan, math.nan, math.nan, 0
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return sum(vals) / len(vals), means[int(0.025 * n)], means[int(0.975 * n) - 1], len(vals)


def summarize(rows, keys, value_cols):
    """Mean and 95% bootstrap CI over jobs for each key (pooled: carga = 'todas'; and per workload)."""
    out = []
    groups = {}
    for r in rows:
        k = tuple(r[c] for c in keys)
        groups.setdefault(("todas",) + k, []).append(r)
        groups.setdefault((r["carga"],) + k, []).append(r)
    for g, rs in sorted(groups.items(), key=lambda x: (x[0][0] != "todas", str(x[0]))):
        rec = {"carga": g[0], **dict(zip(keys, g[1:]))}
        for c in value_cols:
            m, lo, hi, n = boot([r[c] for r in rs])
            rec |= {c: m, f"{c}_ic_inf": lo, f"{c}_ic_sup": hi}
        rec["n_jobs"] = len(rs)
        out.append(rec)
    return out


def main():
    dest = pathlib.Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    by_job = {pathlib.Path(p).stem: list(csv.DictReader(open(p))) for p in sys.argv[2:]}
    used = {}
    for job, rows in sorted(by_job.items()):
        w, rep = workload_rep(job)
        if rows and all(r["status"] == "VALIDA" for r in rows) and (w, rep) not in used:
            used[(w, rep)] = job
        elif rows:
            print(f"skipped {job}: {sum(r['status'] != 'VALIDA' for r in rows)} invalid levels or duplicate")
    tasks = [(v, dest) for job in used.values() for v in by_job[job]]
    with mp.Pool(20) as pool:
        rows = pool.map(level, tasks, chunksize=1)
    rows.sort(key=lambda r: (ORDER.index(r["carga"]), r["rep"], r["config"]))
    write_csv(dest / "niveis.csv", rows)

    vs_base, pre, s3 = [], [], []
    for job in used.values():
        lv = {r["config"]: r for r in rows if r["job"] == job}
        w, rep = workload_rep(job)
        for r in lv.values():
            if not r["nivel_proprio"]:
                continue
            own = r["nivel_proprio"]
            for b in BASES:
                if b in lv:
                    vs_base.append({"carga": w, "rep": rep, "job": job, "politica": r["politica"], "nivel": own,
                                    "preempcao": r["preempcao"], "base": b,
                                    **{f"dif_{x}": r[f"{own}_{x}"] - lv[b][f"{own}_{x}"] for x in VIEWS},
                                    **{f"dif_{x}": r[x] - lv[b][x] for x in OTHER}})
        for p in POLICIES:
            d = {}
            for own in LEVELS:
                a, b = lv.get(f"{p}_{own}_p1"), lv.get(f"{p}_{own}_p0")
                if a and b:
                    d[own] = {x: a[f"{own}_{x}"] - b[f"{own}_{x}"] for x in VIEWS}
                    pre.append({"carga": w, "rep": rep, "job": job, "politica": p, "nivel": own,
                                **{f"dif_{x}": d[own][x] for x in VIEWS},
                                **{f"dif_{x}": a[x] - b[x] for x in OTHER}})
            if "S3k5" in d and "S6k4" in d:
                s3.append({"carga": w, "rep": rep, "job": job, "politica": p,
                           **{f"delta_S3_{x}": d["S3k5"][x] for x in ("comb", "so_ttft")},
                           **{f"delta_S6k4_{x}": d["S6k4"][x] for x in ("comb", "so_ttft")},
                           **{f"interacao_{x}": d["S3k5"][x] - d["S6k4"][x] for x in ("comb", "so_ttft")}})
    write_csv(dest / "vs_base.csv", vs_base)
    write_csv(dest / "preempt.csv", pre)
    write_csv(dest / "s3_hipotese.csv", s3)
    res = []
    res += [{"tabela": "vs_base", **r} for r in summarize(vs_base, ["politica", "nivel", "preempcao", "base"],
                                                          [f"dif_{x}" for x in VIEWS + OTHER])]
    res += [{"tabela": "preempt", **r} for r in summarize(pre, ["politica", "nivel"], [f"dif_{x}" for x in VIEWS + OTHER])]
    res += [{"tabela": "s3_hipotese", **r} for r in summarize(s3, ["politica"],
                                                              [f"{a}_{x}" for a in ("delta_S3", "delta_S6k4", "interacao")
                                                               for x in ("comb", "so_ttft")])]
    write_csv(dest / "resumo.csv", res)
    missing = [(w, r) for w in ORDER for r in (1, 2) if (w, r) not in used]
    print(f"{dest}: {len(rows)} levels from {len(used)} jobs; missing {missing}")


if __name__ == "__main__":
    main()
