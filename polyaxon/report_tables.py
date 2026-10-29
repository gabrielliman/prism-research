"""Markdown result tables for the reports, from summarize_reps.py's metricas.csv. Standard layout of the tables.

Usage: python3 polyaxon/report_tables.py <metricas.csv> [--extra ativacoes|trocas] <selection> [<selection> ...]

A selection is <scenario>/<level> (every configuration, in the order of ORDEM) or <scenario>/<level>/<config>
(one row). Rows come out in the order given; with more than one scenario/level a "Cenário" column is added.
Prints one table to stdout.

Columns: repetitions, served, losses, TTFT p50/p99 and p90, the TTFT-only SLOs of ovl_plots.SLOS_TTFT, the TPOT
SLO, the combined SLO the load generator reports (TTFT and TPOT, with the limits the test used), worst wait for a
model's first token, and one extra column (activations, or throughput swaps / preempted requests). Every SLO is
the fraction of all sent requests, as in overload_load.py: strict "<", unserved and failed requests count as misses.
Needs pandas.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ovl_plots import SLOS_TTFT  # noqa: E402

ORDEM = ["original", "idle25", "idle10", "idle5", "idle1", "idle0.5", "idle0.1", "pressure", "adaptive", "headroom",
         "fair", "tp_P0D0", "tp_P0D1", "tp_P1D0", "tp_P1D1"]
NOME = {"original": "original (50 s)", "pressure": "despejo sob pressão", "adaptive": "ociosidade adaptativa",
        "headroom": "só folga de 3 GB", "fair": "rodízio anti-fome",
        **{f"idle{t}": f"limiar {t.replace('.', ',')} s" for t in ("25", "10", "5", "1", "0.5", "0.1")},
        **{f"tp_{x}": f"troca {x}" for x in ("P0D0", "P0D1", "P1D0", "P1D1")}}
CENARIO = {"ovl_trace_big": {"ts1": "`ovl_trace_big` 1×", "ts0.5": "`ovl_trace_big` 2×"}}
EXTRA = {"ativacoes": ("Ativações", lambda x: n(x["ativações"].mean(), 0)),
         "trocas": ("Trocas / preemptadas",
                    lambda x: f"{n(x['trocas throughput'].mean(), 0)} / {n(x['requisições preemptadas'].mean(), 0)}")}


def n(x, d=1):
    return "nunca" if not np.isfinite(x) else f"{x:.{d}f}".replace(".", ",")


def faixa(v, d=1):
    # mean (min–max) over the repetitions
    return n(v.iloc[0], d) if len(v) == 1 else f"{n(v.mean(), d)} ({n(v.min(), d)}–{n(v.max(), d)})"


def nome_cenario(cen, niv):
    if cen in CENARIO:
        return CENARIO[cen].get(niv, f"`{cen}` {niv}")
    return f"`{cen}` {niv.replace('rate', '').replace('.', ',')}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("metricas")
    p.add_argument("--extra", choices=EXTRA, default="ativacoes")
    p.add_argument("selecao", nargs="+")
    a = p.parse_args()
    m = pd.read_csv(a.metricas)
    linhas = []  # (scenario, level, config)
    for sel in a.selecao:
        cen, niv, *cfg = sel.split("/")
        g = m[(m["cenário"] == cen) & (m["nível"] == niv)]
        cfgs = cfg or [c for c in ORDEM if c in set(g.config)] + sorted(set(g.config) - set(ORDEM))
        linhas += [(cen, niv, c) for c in cfgs]
    varios = len({(c, l) for c, l, _ in linhas}) > 1
    tpot = [c for c in m.columns if c.startswith("SLO TPOT")][0]
    lim_tpot = tpot.removeprefix("SLO TPOT ")
    cols = (["Cenário"] if varios else []) + [
        "Configuração", "Rep.", "Atendidas", "Perdas", "TTFT p50 / p99 (s)", "TTFT p90 (s)",
        *[f"TTFT < {t} s (%)" for t in SLOS_TTFT], f"TPOT {lim_tpot} (%)",
        f"SLO: TTFT < {SLOS_TTFT[0]} s e TPOT {lim_tpot} (%)", "Pior espera pelo 1º token (s)", EXTRA[a.extra][0]]
    print("| " + " | ".join(cols) + " |")
    print("|" + " --- |" * len(cols))
    anterior = None
    for cen, niv, c in linhas:
        x = m[(m["cenário"] == cen) & (m["nível"] == niv) & (m.config == c)]
        if x.empty:
            sys.exit(f"no levels for {cen}/{niv}/{c}")
        perdas = int(x.perdas.sum())
        row = ([nome_cenario(cen, niv) if (cen, niv) != anterior else ""] if varios else []) + [
            NOME.get(c, c), str(len(x)),
            f"{x['atendidas'].sum() / x['enviadas'].sum() * 100:.1f}%".replace(".", ","),
            "—" if perdas == 0 else f"{perdas} ({', '.join(str(int(v)) for v in x.perdas)})",
            f"{n(x['TTFT p50 (s)'].mean(), 2)} / {n(x['TTFT p99 (s)'].mean())}", faixa(x["TTFT p90 (s)"]),
            *[n(100 * x[f"SLO TTFT < {t} s"].mean(), 0) for t in SLOS_TTFT], n(100 * x[tpot].mean(), 0),
            faixa(100 * x["SLO"], 0), faixa(x["pior espera pelo 1º token (s)"], 0), EXTRA[a.extra][1](x)]
        anterior = (cen, niv)
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
