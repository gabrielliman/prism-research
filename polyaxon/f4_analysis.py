#!/usr/bin/env python3
"""F4.4/F4.5 analysis: structural constraints A1 (D34) against the same base policy without them, paired by job.

Usage:
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_analysis.py <dest dir> <validator.csv> [...]

Every job of the campaign (polyaxon/f4_driver.py) runs ONE workload with the four arms A0.1, A0.1_A1, A0.3, A0.3_A1
in the same window (rule 3), so the comparison of "with A1" against "without A1" is paired by job (= repetition).
Only levels the validator classified VALIDA are used (section 0.2); the others are listed apart.

Per level (niveis.csv):
  impasse        T1 frozen time (validator t1_frozen_s) >= IMPASSE_S (60 s, D34): the F4.5 criterion "zero impasses"
  atendidas      served / sent; unserved count
  S1 views       slo_metrics.py at S1 TTFT 1, 2, 5 s with TPOT 100 ms (report table standard, CLAUDE.md rule 7):
                 combined at 1 s, TTFT-only at 1/2/5 s, TPOT-only at 100 ms; violation breakdown at 1 s
  TTFT           p50/p90/p99 of the served (s)
  tail (D33)     wait = TTFT if served, else the run's end (elapsed_s: load + drain window) minus the arrival;
                 wait p99, max, and the fraction of requests whose wait exceeds 10x the level's median wait
  events         A1.2 firings (evict_deadlock), activations/min, throughput swaps, idle evictions
Paired (pareado.csv): per job and base policy, (with A1) - (without A1) for each metric.
Summary (resumo.md): per workload and base policy, mean difference with a 95% bootstrap CI over the jobs (paired),
and the impasse count per arm. "Significant" = the CI excludes 0 (with 2 reps the CI is only indicative).
"""
import csv
import json
import math
import pathlib
import random
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_ovl  # noqa: E402
import slo_metrics as sm  # noqa: E402

IMPASSE_S = 100.0  # D37 (Gabriel, 2026-11-06)
SPECS = {1: "S1:ttft=1,tpot=0.1", 2: "S1:ttft=2,tpot=0.1", 5: "S1:ttft=5,tpot=0.1"}
ARMS = {"A0.1": ("A0.1", False), "A0.1_A1": ("A0.1", True), "A0.3": ("A0.3", False), "A0.3_A1": ("A0.3", True),
        "A0.3_A1h0": ("A0.3", True)}  # h0: A0.3 + A1 with activation headroom 0 (headroom check, D37)
# paired comparisons: label -> (without, with); the difference is with − without, in the same job
PAIRS = {"A0.1": ("A0.1", "A0.1_A1"), "A0.3": ("A0.3", "A0.3_A1"), "A0.3 (A1 com folga 0)": ("A0.3", "A0.3_A1h0"),
         "folga 0 × folga 3 (com A1)": ("A0.3_A1", "A0.3_A1h0")}
# metrics compared, their label, scale and whether higher is better
METRICS = [
    ("impasse", "impasse (0/1)", 1, False),
    ("t1_frozen_s", "T1 congelado (s)", 1, False),
    ("atendidas", "atendidas (pp)", 100, True),
    ("comb_1s", "combinado 1 s (pp)", 100, True),
    ("ttft_1s", "só TTFT 1 s (pp)", 100, True),
    ("ttft_2s", "só TTFT 2 s (pp)", 100, True),
    ("ttft_5s", "só TTFT 5 s (pp)", 100, True),
    ("tpot_100ms", "só TPOT 100 ms (pp)", 100, True),
    ("ttft_p50", "TTFT p50 (s)", 1, False),
    ("ttft_p90", "TTFT p90 (s)", 1, False),
    ("espera_p99", "espera p99 (s)", 1, False),
    ("espera_max", "espera máx. (s)", 1, False),
    ("frac_10x_mediana", "> 10× mediana (pp)", 100, False),
]


def workload_rep(job):
    m = re.match(r"f4-(?:folga-)?(\w+?)-(\d+)[a-z]?$", job)  # f4-c3-1, f4-c10-1b (rerun), f4-folga-t3-1
    return (m.group(1).upper().replace("N", "n"), int(m.group(2))) if m else (job, 0)


def events(lvl):
    ev = list(csv.DictReader(open(lvl / "events.csv"))) if (lvl / "events.csv").exists() else []
    count = lambda k: sum(e["kind"] == k for e in ev)
    return {"disparos_a12": count("evict_deadlock"), "ativacoes": count("act_req"), "trocas": count("evict_swap"),
            "despejos_ocio": count("evict")}


def tail(lvl, elapsed):
    reqs, _, _ = sm.load_level(lvl)
    waits = [r["ttft"] if r["status"] == "ok" else max(0.0, elapsed - r["arrival"]) for r in reqs]
    med = sm.pct(waits, 50)
    return {"espera_p99": sm.pct(waits, 99), "espera_max": max(waits) if waits else math.nan,
            "frac_10x_mediana": sum(w > 10 * med for w in waits) / len(waits) if waits else math.nan}


def level_row(v, dest, refs):
    src = pathlib.Path(v["root"]) / v["level"]  # <job dir>/outputs/<config>/<step>/<level>
    cfg, step, lvl = src.parts[-3], src.parts[-2], src.parts[-1]
    job = pathlib.Path(v["root"]).name
    out = dest / "levels" / job / cfg / step / lvl
    if not (out / "requests.csv").exists():
        extract_ovl.extract_level(str(src), str(out))
    if not (out.parent / "config.json").exists():
        shutil.copy(src.parents[1] / "configs" / f"{step}.json", out.parent / "config.json")
    s = json.load(open(out / "summary.json"))
    ms = {k: m for k, m in zip(SPECS, sm.level_metrics(out, list(SPECS.values()), refs))}
    w, rep = workload_rep(job)
    t1 = float(v["t1_frozen_s"] or 0)
    m1 = ms[1]
    return {"job": job, "carga": w, "rep": rep, "config": cfg, "base": ARMS.get(cfg, (cfg, None))[0],
            "com_a1": ARMS.get(cfg, (cfg, None))[1], "cenário": step, "nível": lvl, "uuid": v["uuid"],
            "t1_frozen_s": t1, "impasse": int(t1 >= IMPASSE_S), "enviadas": s["sent"],
            "atendidas": s["ok"] / s["sent"], "nao_atendidas_n": s["unserved"],
            "comb_1s": m1["comb"], "ttft_1s": m1["so_ttft"], "ttft_2s": ms[2]["so_ttft"], "ttft_5s": ms[5]["so_ttft"],
            "tpot_100ms": m1["so_tpot"], "ambos_ok": m1["ambos_ok"], "viola_so_ttft": m1["viola_so_ttft"],
            "viola_so_tpot": m1["viola_so_tpot"], "viola_ambos": m1["viola_ambos"],
            "ttft_p50": m1["ttft_p50"], "ttft_p90": m1["ttft_p90"], "ttft_p99": m1["ttft_p99"],
            **tail(out, s["elapsed_s"]), **events(out),
            "ativacoes_min": 60 * events(out)["ativacoes"] / (s["elapsed_s"] or 1)}


def boot_ci(xs, n=10000, seed=1):
    if len(xs) < 2:
        return (math.nan, math.nan)
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def fmt(x, scale=1, d=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * scale:.{d}f}".replace(".", ",")


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)


def main():
    dest = pathlib.Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    refs = sm.Refs(cat="/nonexistent")  # S1 only: no Ĉ_at split (C10 models are not in model_info.json)
    rows, dropped = [], []
    for vcsv in sys.argv[2:]:
        for v in csv.DictReader(open(vcsv)):
            if v["status"] != "VALIDA":
                dropped.append({"validador": vcsv, **v})
                continue
            rows.append(level_row(v, dest, refs))
    write_csv(dest / "niveis.csv", rows)
    write_csv(dest / "descartados.csv", dropped)

    by_job = {}
    for r in rows:
        by_job.setdefault((r["carga"], r["rep"], r["job"]), {})[r["config"]] = r
    pares = []
    for (w, rep, job), cfgs in sorted(by_job.items()):
        for base, (wo, wi) in PAIRS.items():
            a, b = cfgs.get(wo), cfgs.get(wi)
            if not (a and b):
                continue
            pares.append({"carga": w, "rep": rep, "job": job, "base": base,
                          **{f"sem_{k}": a[k] for k, *_ in METRICS}, **{f"com_{k}": b[k] for k, *_ in METRICS},
                          **{f"dif_{k}": b[k] - a[k] for k, *_ in METRICS}})
    write_csv(dest / "pareado.csv", pares)

    order = ["C3", "C1n8", "C1n14", "C2", "T1", "C6", "C7", "C8", "T3", "C10"]
    loads = sorted({r["carga"] for r in rows}, key=lambda w: order.index(w) if w in order else 99)
    md = ["# F4.4 — restrições estruturais (A1): com × sem, pareado por job", "",
          "Gerado por `polyaxon/f4_analysis.py`. Só níveis VALIDA "
          f"({len(rows)} usados, {len(dropped)} descartados, lista em `descartados.csv`). Impasse = T1 ≥ "
          f"{IMPASSE_S:.0f} s (D34). SLO S1: TTFT 1/2/5 s, TPOT 100 ms, frações sobre todas as enviadas. "
          "Espera = TTFT, ou fim da janela − chegada para as não atendidas (D33).", "",
          "## Impasses e médias por braço", "",
          "| carga | braço | reps | impasses | T1 médio (s) | atendidas (%) | comb. 1 s (%) | TTFT 1/2/5 s (%) "
          "| TPOT 100 ms (%) | TTFT p50/p90 (s) | espera p99/máx. (s) | > 10× med. (%) | disparos A1.2 | ativações/min |",
          "|" + " --- |" * 14]
    mean = lambda xs: sum(xs) / len(xs) if xs else math.nan
    for w in loads:
        for cfg in ARMS:
            rs = [r for r in rows if r["carga"] == w and r["config"] == cfg]
            if not rs:
                continue
            g = lambda k: mean([r[k] for r in rs])
            md.append(f"| {w} | {cfg} | {len(rs)} | {sum(r['impasse'] for r in rs)} | {fmt(g('t1_frozen_s'), 1, 0)} | "
                      f"{fmt(g('atendidas'), 100)} | {fmt(g('comb_1s'), 100)} | {fmt(g('ttft_1s'), 100)} / "
                      f"{fmt(g('ttft_2s'), 100)} / {fmt(g('ttft_5s'), 100)} | {fmt(g('tpot_100ms'), 100)} | "
                      f"{fmt(g('ttft_p50'))} / {fmt(g('ttft_p90'))} | {fmt(g('espera_p99'), 1, 0)} / "
                      f"{fmt(g('espera_max'), 1, 0)} | {fmt(g('frac_10x_mediana'), 100)} | "
                      f"{fmt(g('disparos_a12'))} | {fmt(g('ativacoes_min'), 1, 2)} |")
    md += ["", "## Diferença pareada (com A1 − sem A1), média e IC 95% por bootstrap sobre os jobs", "",
           "Sinal: `+` melhora quando maior é melhor (pp de SLO, atendidas); nos tempos e na cauda, negativo é "
           "melhora. `*` = IC exclui 0.", ""]
    for base in [b for b in PAIRS if any(p["base"] == b for p in pares)]:
        md += [f"### {base}: {PAIRS[base][1]} − {PAIRS[base][0]}", "",
               "| carga | jobs | " + " | ".join(lbl for k, lbl, *_ in METRICS if k != "impasse") + " |",
               "|" + " --- |" * (1 + len(METRICS))]
        for w in loads:
            ps = [p for p in pares if p["carga"] == w and p["base"] == base]
            if not ps:
                continue
            cells = []
            for k, _, scale, _ in METRICS:
                if k == "impasse":
                    continue
                ds = [p[f"dif_{k}"] for p in ps if not math.isnan(p[f"dif_{k}"])]
                lo, hi = boot_ci(ds)
                star = "*" if not math.isnan(lo) and (lo > 0 or hi < 0) else ""
                cells.append(f"{fmt(mean(ds), scale)}{star} [{fmt(lo, scale)}; {fmt(hi, scale)}]")
            md.append(f"| {w} | {len(ps)} | " + " | ".join(cells) + " |")
        md.append("")
    (dest / "resumo.md").write_text("\n".join(md) + "\n")
    print(f"{dest}: {len(rows)} levels, {len(pares)} pairs, {len(dropped)} dropped")


if __name__ == "__main__":
    sys.exit(main())
