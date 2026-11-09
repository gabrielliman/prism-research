#!/usr/bin/env python3
"""F6.0 per-model view (fairness between models): does a policy trade total attainment for the worst-served models?

Usage (after polyaxon/f60_analysis.py, which extracts the levels):
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f60_fairness.py <analysis dir>

For every level of <analysis dir>/niveis.csv and each F6.0 SLO level (S3 kA=5, S6 kR=1, S6 kR=4), per model: TTFT-only
and combined attainment (slo_metrics.evaluate per_model), p90 TTFT of the served requests, and the largest wait
(TTFT, or end of the run window − arrival for the unserved, D33). Summaries per level: worst model, mean of the worst
quarter of the models (at least 2), median model, Jain's index of the per-model attainment (1 = every model served
alike; R5/R6-style fairness view, D31: the worst model is an observation, not the objective), worst model's p90 TTFT
and worst model's largest wait. Only models with at least MIN_REQS requests count (the Zipf tail of the popularity
workload has models with a handful of requests). Output: modelos.csv (per model), justica.csv (per level),
justica_pareado.csv (arm − baseline at the arm's own level, per job), justica_resumo.csv (mean, 95% bootstrap CI over
jobs, pooled and per workload).
"""
import csv
import json
import math
import multiprocessing as mp
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slo_metrics as sm  # noqa: E402
from f5_analysis import write_csv  # noqa: E402
from f60_analysis import LEVELS, BASES, summarize  # noqa: E402

MIN_REQS = 10
COLS = ["pior_ttft", "quartil_ttft", "mediana_ttft", "jain_ttft", "pior_comb", "quartil_comb", "pior_p90_s",
        "pior_espera_s"]


def jain(xs):
    return (sum(xs) ** 2) / (len(xs) * sum(x * x for x in xs)) if xs and any(xs) else math.nan


def level(args):
    row, root = args
    lvl = root / "levels" / row["job"] / row["config"] / row["cenário"] / row["nível"]
    refs = sm.Refs()
    reqs, ev, conf = sm.load_level(lvl)
    sc = sm.ded_scenario(lvl)
    s = json.load(open(lvl / "summary.json"))
    by = {}
    for r in reqs:
        by.setdefault(r["model"], []).append(r)
    keep = {m for m, rs in by.items() if len(rs) >= MIN_REQS}
    per_model, summ = [], {}
    for k, spec in LEVELS.items():
        m = sm.evaluate(reqs, ev, conf, spec, refs, True, sc)["por_modelo"]
        for name, v in m.items():
            if name not in keep:
                continue
            rs = by[name]
            served = sorted(r["ttft"] for r in rs if r["status"] == "ok")
            waits = [r["ttft"] if r["status"] == "ok" else max(0.0, s["elapsed_s"] - r["arrival"]) for r in rs]
            per_model.append({k2: row[k2] for k2 in ("job", "carga", "rep", "config")} |
                             {"nivel": k, "modelo": name, "n": len(rs), "so_ttft": v["so_ttft"], "comb": v["comb"],
                              "ttft_p90": sm.pct(served, 90) if served else math.nan, "espera_max": max(waits)})
        pm = [x for x in per_model if x["nivel"] == k]
        tt = sorted(x["so_ttft"] for x in pm)
        cb = sorted(x["comb"] for x in pm)
        q = max(2, len(tt) // 4)
        summ[k] = {"pior_ttft": tt[0], "quartil_ttft": sum(tt[:q]) / q, "mediana_ttft": tt[len(tt) // 2],
                   "jain_ttft": jain(tt), "pior_comb": cb[0], "quartil_comb": sum(cb[:q]) / q,
                   "pior_p90_s": max(x["ttft_p90"] for x in pm if not math.isnan(x["ttft_p90"])),
                   "pior_espera_s": max(x["espera_max"] for x in pm), "modelos": len(pm)}
    return per_model, {k2: row[k2] for k2 in ("job", "carga", "rep", "config", "politica", "nivel_proprio",
                                               "preempcao")} | {f"{k}_{c}": v for k, d in summ.items()
                                                                for c, v in d.items()}


def main():
    root = pathlib.Path(sys.argv[1])
    rows = list(csv.DictReader(open(root / "niveis.csv")))
    with mp.Pool(20) as pool:
        res = pool.map(level, [(r, root) for r in rows], chunksize=1)
    write_csv(root / "modelos.csv", [m for pm, _ in res for m in pm])
    lv = [x for _, x in res]
    write_csv(root / "justica.csv", lv)
    by_job = {}
    for x in lv:
        by_job.setdefault(x["job"], {})[x["config"]] = x
    pares = []
    for job, cfgs in by_job.items():
        for c, x in cfgs.items():
            own = x["nivel_proprio"]
            if not own:
                continue
            for b in BASES:
                if b in cfgs:
                    pares.append({"carga": x["carga"], "rep": x["rep"], "job": job, "politica": x["politica"],
                                  "nivel": own, "preempcao": x["preempcao"], "base": b,
                                  **{f"dif_{col}": float(x[f"{own}_{col}"]) - float(cfgs[b][f"{own}_{col}"])
                                     for col in COLS}})
    write_csv(root / "justica_pareado.csv", pares)
    write_csv(root / "justica_resumo.csv",
              summarize(pares, ["politica", "nivel", "preempcao", "base"], [f"dif_{c}" for c in COLS]))
    print(f"{root}: {len(lv)} levels, {len(pares)} paired rows")


if __name__ == "__main__":
    main()
