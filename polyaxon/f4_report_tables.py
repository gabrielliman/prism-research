#!/usr/bin/env python3
"""Compact markdown tables of the F04 report from f4_analysis.py's niveis.csv and pareado.csv.

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_report_tables.py [<campaign dir>]
Prints three tables: (1) impasses per arm, (2) the arms side by side (report column standard: combined 1 s,
TTFT-only 1/2/5 s, TPOT-only 100 ms, TTFT p50/p90, tail), (3) paired difference with A1 − without A1, mean and 95%
bootstrap CI over jobs, for the main views (* = CI excludes 0).
"""
import math
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from f4_analysis import IMPASSE_S, boot_ci  # noqa: E402

CAMP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "reports/data/F04/campanha")
ORDER = ["C3", "C1n8", "C1n14", "C2", "T1", "C6", "C7", "C8", "T3", "C10"]
ARMS = ["A0.1", "A0.1_A1", "A0.3", "A0.3_A1", "A0.3_A1h0"]


def f(x, d=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}".replace(".", ",")


def main():
    n = pd.read_csv(CAMP / "niveis.csv")
    p = pd.read_csv(CAMP / "pareado.csv")
    loads = [w for w in ORDER if w in set(n.carga)]

    print(f"**Impasses (níveis com T1 ≥ {IMPASSE_S:.0f} s / níveis VALIDA)**\n")
    print("| Carga | " + " | ".join(ARMS) + " |")
    print("|" + " --- |" * (len(ARMS) + 1))
    for w in loads:
        cells = []
        for a in ARMS:
            g = n[(n.carga == w) & (n.config == a)]
            cells.append(f"{int(g.impasse.sum())}/{len(g)}" if len(g) else "–")
        print(f"| {w} | " + " | ".join(cells) + " |")

    print("\n**Médias por braço** (S1; frações sobre todas as enviadas, em %; tempos em s)\n")
    print("| Carga | Braço | Atendidas | Comb. 1 s | TTFT 1 / 2 / 5 s | TPOT 100 ms | TTFT p50 / p90 | "
          "Espera p99 / máx. | Disparos A1.2 | Ativações/min |")
    print("|" + " --- |" * 10)
    for w in loads:
        for a in ARMS:
            g = n[(n.carga == w) & (n.config == a)]
            if not len(g):
                continue
            m = g.mean(numeric_only=True)
            print(f"| {w} | {a} | {f(100 * m.atendidas)} | {f(100 * m.comb_1s)} | {f(100 * m.ttft_1s)} / "
                  f"{f(100 * m.ttft_2s)} / {f(100 * m.ttft_5s)} | {f(100 * m.tpot_100ms)} | {f(m.ttft_p50)} / "
                  f"{f(m.ttft_p90)} | {f(m.espera_p99, 0)} / {f(m.espera_max, 0)} | {f(m.disparos_a12)} | "
                  f"{f(m.ativacoes_min, 2)} |")

    cols = [("atendidas", 100, "Atendidas (pp)"), ("comb_1s", 100, "Comb. 1 s (pp)"),
            ("ttft_2s", 100, "TTFT 2 s (pp)"), ("tpot_100ms", 100, "TPOT 100 ms (pp)"),
            ("ttft_p90", 1, "TTFT p90 (s)"), ("espera_p99", 1, "Espera p99 (s)")]
    print("\n**Diferença pareada com A1 − sem A1** (média [IC 95%]; `*` = IC exclui 0; SLO e atendidas: + é melhor; "
          "tempos: − é melhor)\n")
    print("| Base | Carga | Jobs | " + " | ".join(c[2] for c in cols) + " |")
    print("|" + " --- |" * (len(cols) + 3))
    for base in list(dict.fromkeys(p.base)):
        for w in loads:
            g = p[(p.carga == w) & (p.base == base)]
            if not len(g):
                continue
            cells = []
            for k, s, _ in cols:
                ds = [x for x in g[f"dif_{k}"].tolist() if not math.isnan(x)]
                lo, hi = boot_ci(ds)
                star = "*" if not math.isnan(lo) and (lo > 0 or hi < 0) else ""
                cells.append(f"{f(s * sum(ds) / len(ds))}{star} [{f(s * lo)}; {f(s * hi)}]")
            print(f"| {base} | {w} | {len(g)} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
