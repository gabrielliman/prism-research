#!/usr/bin/env python3
"""F5.2 analysis: the baseline campaign (D39, D46) under the new methodology, paired by job.

Usage:
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f5_analysis.py <dest dir> <validator.csv> [...]

Every job of the campaign (polyaxon/f5_suites.sh, polyaxon/f4_driver.py) runs ONE workload with the five
configurations A0.1, A0.1_A1, A0.2_A1, A0.4, A0.4p in the same window (rule 3), so the comparison between
configurations is paired by job (= repetition). For each (workload, repetition) the job with its 5 levels VALIDA is
used (the partly invalid jobs replaced by re-runs, D47/D48, are listed in descartados.csv); a job is never mixed with
its replacement. Workload = the job name (f5-c1n14-2 -> C1n14), since several workloads share a step (ovl_mem: C1 with
10/14/19 models; ovl_classes: C9 on C1 and on C6).

Per level (niveis.csv):
  S1 views     TTFT-only at 1/2/5 s, TPOT-only at 100 ms, combined at 1 s (report standard, CLAUDE.md rule 7), and the
               violation breakdown at 1 s (both / only TTFT / only TPOT / unserved)
  S2 k_T=10, k_D=5 (main family, strict reference, D32) and S6 / S6P k_R=1, k_D=5 (rotation-time families, D42):
               the three views, the F5.0c split of the TTFT misses (D43) and the old one (Ĉ_at only), TPOT misses
               during a transition, the worst model's combined attainment (S2)
  TTFT         p50/p90/p99 of the served (s); tail (D33): wait = TTFT, or the end of the run window − arrival for the
               unserved; p99, max, fraction above 10× the level's median
  freeze       T1 frozen time (validator t1_frozen_s) and impasse = T1 ≥ 100 s (D37)
  events       activations/min (act_ok), throughput swaps, idle evictions, A1.2 firings, preempted requests
  idleness     polyaxon/gpu_idle.py (D44, D46): idle residency with pending demand, wasted memory time, expected
               (GPU-busy ρ) vs observed idleness, active / expected / resident model counts, idle fraction per model
Curves (curvas_niveis.csv, F5.2a): every level under a grid of SLO families (S1; S2 and S2M k_T × k_D; S3 k_A × k_D;
S6 and S6P k_R × k_D), the three views and the new split. Paired (pareado.csv): per job, each configuration minus the
reference A0.1_A1 (Prism + A1, D38) for the main metrics.
"""
import csv
import json
import math
import multiprocessing as mp
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_ovl  # noqa: E402
import gpu_idle  # noqa: E402
import slo_metrics as sm  # noqa: E402

IMPASSE_S = 100.0  # D37
CONFIGS = ["A0.1", "A0.1_A1", "A0.2_A1", "A0.4", "A0.4p"]
REF = "A0.1_A1"
ORDER = ["C1n10", "C1n14", "C1n19", "C6n10", "C6n14", "C6n19", "C2", "C3", "T1", "C7", "C8", "C9C1", "C9C6", "T3",
         "T2", "C10", "C4", "C5"]
S1 = {1: "S1:ttft=1,tpot=0.1", 2: "S1:ttft=2,tpot=0.1", 5: "S1:ttft=5,tpot=0.1"}
MAIN = {"s2": "S2:kT=10,kD=5", "s6": "S6:kR=1,kD=5", "s6p": "S6P:kR=1,kD=5"}
SPLIT = ("inev_ativacao", "inev_rotacao", "evit_residencia", "evit")
KT, KD = (2, 5, 10, 25, 50, 100), (1.5, 2, 3, 5, 10, 20)
KA, KR, KD2 = (0.5, 1, 2, 5, 10, 25, 50), (0.5, 1, 2, 4, 8), (5, 10)


def grid():
    out = [("S1", 1, 0.1, S1[1])]
    out += [(f, kt, kd, f"{f}:kT={kt},kD={kd}") for f in ("S2", "S2M") for kt in KT for kd in KD]
    out += [("S3", ka, kd, f"S3:kA={ka},kD={kd}") for ka in KA for kd in KD2]
    out += [(f, kr, kd, f"{f}:kR={kr},kD={kd}") for f in ("S6", "S6P") for kr in KR for kd in KD2]
    return out


def workload_rep(job):
    m = re.match(r"f5-(\w+?)-(\d+)[a-z]?$", job)
    w = m.group(1).upper().replace("N1", "n1").replace("C9C", "C9C")
    return {"C1N10": "C1n10", "C1N14": "C1n14", "C1N19": "C1n19", "C6N10": "C6n10", "C6N14": "C6n14",
            "C6N19": "C6n19"}.get(w, w), int(m.group(2))


def events(lvl):
    ev = list(csv.DictReader(open(lvl / "events.csv"))) if (lvl / "events.csv").exists() else []
    count = lambda k: sum(e["kind"] == k for e in ev)
    pre = sum(float(e["value"] or 0) for e in ev if e["kind"] == "preempt")
    return {"ativacoes": count("act_ok"), "trocas": count("evict_swap"), "despejos_ocio": count("evict"),
            "disparos_a12": count("evict_deadlock"), "preemptadas": pre}


def tail(reqs, elapsed):
    waits = [r["ttft"] if r["status"] == "ok" else max(0.0, elapsed - r["arrival"]) for r in reqs]
    med = sm.pct(waits, 50)
    return {"espera_p99": sm.pct(waits, 99), "espera_max": max(waits) if waits else math.nan,
            "frac_10x_mediana": sum(w > 10 * med for w in waits) / len(waits) if waits else math.nan}


def extract(v, dest):
    src = pathlib.Path(v["root"]) / v["level"]  # <job dir>/outputs/<config>/<step>/<level>
    cfg, step, lvl = src.parts[-3], src.parts[-2], src.parts[-1]
    out = dest / "levels" / pathlib.Path(v["root"]).name / cfg / step / lvl
    if not (out / "requests.csv").exists():
        extract_ovl.extract_level(str(src), str(out))
    if not (out.parent / "config.json").exists():
        shutil.copy(src.parents[1] / "configs" / f"{step}.json", out.parent / "config.json")
    return out, cfg, step, lvl


def level(args):
    v, dest = args
    refs = sm.Refs()
    out, cfg, step, lvl = extract(v, dest)
    job = pathlib.Path(v["root"]).name
    w, rep = workload_rep(job)
    s = json.load(open(out / "summary.json"))
    reqs, ev, conf = sm.load_level(out)
    sc = sm.ded_scenario(out)
    key = {"job": job, "carga": w, "rep": rep, "config": cfg, "cenário": step, "nível": lvl, "uuid": v["uuid"]}
    m1 = {k: sm.evaluate(reqs, ev, conf, spec, refs, False, sc) for k, spec in S1.items()}
    mm = {k: sm.evaluate(reqs, ev, conf, spec, refs, k == "s2", sc) for k, spec in MAIN.items()}
    t1 = float(v["t1_frozen_s"] or 0)
    e = events(out)
    row = {**key, "t1_frozen_s": t1, "impasse": int(t1 >= IMPASSE_S), "enviadas": s["sent"],
           "atendidas": s["ok"] / s["sent"], "nao_atendidas_n": s["unserved"],
           "comb_1s": m1[1]["comb"], "ttft_1s": m1[1]["so_ttft"], "ttft_2s": m1[2]["so_ttft"],
           "ttft_5s": m1[5]["so_ttft"], "tpot_100ms": m1[1]["so_tpot"], "ambos_ok_1s": m1[1]["ambos_ok"],
           "viola_so_ttft_1s": m1[1]["viola_so_ttft"], "viola_so_tpot_1s": m1[1]["viola_so_tpot"],
           "viola_ambos_1s": m1[1]["viola_ambos"], "nao_atendidas": m1[1]["nao_atendidas"],
           "ttft_p50": m1[1]["ttft_p50"], "ttft_p90": m1[1]["ttft_p90"], "ttft_p99": m1[1]["ttft_p99"],
           "chegou_inativo": m1[1]["chegou_inativo"], **tail(reqs, s["elapsed_s"]), **e,
           "ativacoes_min": 60 * e["ativacoes"] / (s["elapsed_s"] or 1),
           "trocas_min_janela": 60 * e["ativacoes"] / (s["args"].get("duration") or s["elapsed_s"] or 1)}
    for k, m in mm.items():
        row |= {f"{k}_comb": m["comb"], f"{k}_ttft": m["so_ttft"], f"{k}_tpot": m["so_tpot"],
                **{f"{k}_{g}": m.get(f"viol_ttft_{g}", math.nan) for g in SPLIT},
                f"{k}_inev_antiga": m.get("viol_ttft_inevitavel", math.nan)}
    row |= {"s2_viol_tpot_em_troca": mm["s2"].get("viol_tpot_em_troca", math.nan),
            "s2_pior_modelo": mm["s2"]["pior_modelo_comb"], "s2_ttft_norm_p50": mm["s2"]["ttft_norm_p50"],
            "s2_ttft_norm_p90": mm["s2"]["ttft_norm_p90"], "s2_tpot_norm_p50": mm["s2"]["tpot_norm_p50"],
            "s2_tpot_norm_p90": mm["s2"]["tpot_norm_p90"]}
    row |= {f"idle_{k}": x for k, x in gpu_idle.level(out, refs).items()}
    curves = []
    for fam, k, kd, spec in grid():
        m = sm.evaluate(reqs, ev, conf, spec, refs, False, sc)
        curves.append({**key, "família": fam, "k": k, "k_D": kd, "comb": m["comb"], "so_ttft": m["so_ttft"],
                       "so_tpot": m["so_tpot"], **{g: m.get(f"viol_ttft_{g}", math.nan) for g in SPLIT}})
    return row, curves


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)


PAIRED = ["atendidas", "comb_1s", "ttft_1s", "ttft_2s", "ttft_5s", "tpot_100ms", "s2_comb", "s2_ttft", "s2_tpot",
          "s6_comb", "s6_ttft", "s6p_comb", "s6p_ttft", "ttft_p50", "ttft_p90", "espera_p99", "espera_max",
          "frac_10x_mediana", "t1_frozen_s", "impasse", "ativacoes_min", "s2_pior_modelo",
          "idle_ocio_observada", "idle_ocio_politica", "idle_ocio_residente_demanda", "idle_ocio_residente_total"]


def main():
    dest = pathlib.Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    by_job = {}
    for vcsv in sys.argv[2:]:
        rows = list(csv.DictReader(open(vcsv)))
        job = pathlib.Path(vcsv).stem
        by_job[job] = rows
    used, dropped = {}, []
    for job, rows in sorted(by_job.items()):
        w, rep = workload_rep(job)
        full = len(rows) == 5 and all(r["status"] == "VALIDA" for r in rows)
        if full and (w, rep) not in used:
            used[(w, rep)] = job
        else:
            dropped += [{"job": job, "carga": w, "rep": rep, "motivo": "job substituído (D47/D48)" if not full
                         else "duplicado", **{k: r.get(k, "") for k in ("level", "status", "motivo")}} for r in rows]
    tasks = [(v, dest) for (w, rep), job in sorted(used.items()) for v in by_job[job]]
    with mp.Pool(20) as pool:
        res = pool.map(level, tasks, chunksize=1)
    rows = sorted((r for r, _ in res), key=lambda r: (ORDER.index(r["carga"]), r["rep"], CONFIGS.index(r["config"])))
    write_csv(dest / "niveis.csv", rows)
    write_csv(dest / "curvas_niveis.csv", [c for _, cs in res for c in cs])
    write_csv(dest / "descartados.csv", dropped)
    pares = []
    for (w, rep), job in sorted(used.items()):
        cfgs = {r["config"]: r for r in rows if r["job"] == job}
        for c in CONFIGS:
            if c != REF and c in cfgs and REF in cfgs:
                pares.append({"carga": w, "rep": rep, "job": job, "config": c,
                              **{f"dif_{k}": cfgs[c][k] - cfgs[REF][k] for k in PAIRED}})
    write_csv(dest / "pareado.csv", pares)
    missing = [(w, r) for w in ORDER for r in (1, 2, 3) if (w, r) not in used]
    print(f"{dest}: {len(rows)} levels from {len(used)} jobs, {len(dropped)} levels dropped, missing {missing}")


if __name__ == "__main__":
    main()
