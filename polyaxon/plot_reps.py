"""Repetition summary: SLO and TTFT p90 of every configuration, one dot per repetition and a bar at the mean.

Usage: python3 polyaxon/plot_reps.py <data dir> <figure dir>

Reads <data dir>/metricas.csv (summarize_reps.py) and writes <figure dir>/resumo__<scenario>__<level>.png.
Configurations are colored by family: Prism's original policy, idle thresholds, simple strategies and the
throughput-per-GB swap. Needs pandas and matplotlib.
"""
import os
import pathlib
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ovl_plots as op  # noqa: E402,F401  (matplotlib style)

ORDEM = ["original", "idle25", "idle10", "idle5", "idle1", "idle0.5", "idle0.1", "pressure", "adaptive",
         "headroom", "fair", "tp_P0D0", "tp_P0D1", "tp_P1D0", "tp_P1D1"]
NOMES = {"original": "original\n(50 s)", "pressure": "pressão", "adaptive": "adaptativa", "headroom": "folga",
         "fair": "rodízio", **{f"idle{t}": f"{t} s" for t in ("25", "10", "5", "1", "0.5", "0.1")},
         **{f"tp_{pd_}": pd_ for pd_ in ("P0D0", "P0D1", "P1D0", "P1D1")}}
FAMILIAS = [("política original", "#52514e"), ("limiar de ociosidade", "#2a78d6"),
            ("estratégia simples", "#1baf7a"), ("troca por throughput", "#eb6834")]


def familia(cfg):
    if cfg == "original":
        return 0
    return 1 if cfg.startswith("idle") else 3 if cfg.startswith("tp_") else 2


def main():
    data, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(data / "metricas.csv")
    for (cen, niv), g in m.groupby(["cenário", "nível"]):
        cfgs = [c for c in ORDEM if c in set(g.config)]
        fig, axes = plt.subplots(2, 1, figsize=(1.0 * len(cfgs) + 2.5, 5.6), sharex=True)
        for ax, col, rot, esc in ((axes[0], "SLO", "SLO atingido (%)", 100), (axes[1], "TTFT p90 (s)", "TTFT p90 (s)", 1)):
            for x, c in enumerate(cfgs):
                v = g[g.config == c][col] * esc
                cor = FAMILIAS[familia(c)][1]
                ax.hlines(v.mean(), x - 0.3, x + 0.3, color=cor, lw=2.5)
                ax.scatter([x] * len(v), v, s=36, color=cor, edgecolor="white", linewidth=1.2, zorder=3)
            ax.set_ylabel(rot)
            ax.set_ylim(bottom=0)
        axes[0].set_title(f"{cen} · {niv}: um ponto por repetição, traço na média")
        axes[1].set_xticks(range(len(cfgs)), [NOMES.get(c, c) for c in cfgs])
        usadas = sorted({familia(c) for c in cfgs})
        fig.legend([plt.Line2D([], [], color=FAMILIAS[i][1], marker="o", lw=2.5) for i in usadas],
                   [FAMILIAS[i][0] for i in usadas], loc="lower center", ncol=len(usadas), bbox_to_anchor=(0.5, -0.01))
        fig.tight_layout(rect=(0, 0.05, 1, 1))
        fig.savefig(out / f"resumo__{cen}__{niv}.png", bbox_inches="tight")
        plt.close(fig)
        print(out / f"resumo__{cen}__{niv}.png")


if __name__ == "__main__":
    main()
