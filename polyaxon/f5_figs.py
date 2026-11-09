#!/usr/bin/env python3
"""Figures of the F05 report from f5_analysis.py's niveis.csv and curvas_niveis.csv.

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f5_figs.py [<campaign dir>] [<figure dir>]
  fig_rho_mem.png     ρ_mem sweep (10/14/19 models) on C1 and C6: S6 TTFT-only, TTFT p90, maximum wait, policy
                      idleness, per configuration (mean of 3 repetitions)
  fig_curvas.png      TTFT-only attainment vs the SLO level (S2 k_T, S6 k_R, S6P k_R), mean over the workloads with
                      residency contention (all but the controls C4 and C5)
  fig_violacoes.png   S2 (k_T=10, k_D=5) TTFT misses split by cause (D43) per configuration, same workloads
  fig_ociosidade.png  observed GPU idleness split into what the load explains and the policy's part (D46)
Palette: the validated categorical slots of the dataviz reference (fixed order, one per configuration), with a
distinct marker per configuration as secondary encoding (5 series > the 3-series all-pairs cap).
"""
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from f5_analysis import CONFIGS  # noqa: E402

CAMP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "reports/data/F05/campanha")
FIG = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "reports/figs/F05")
COLORS = dict(zip(CONFIGS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))
MARKERS = dict(zip(CONFIGS, ["o", "s", "^", "D", "v"]))
LABEL = {"A0.1": "Prism original (sem A1)", "A0.1_A1": "Prism + A1", "A0.2_A1": "limiar 10 s + A1",
         "A0.4": "troca por throughput + A1", "A0.4p": "troca com preempção + A1"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
CONTROLS = {"C4", "C5"}


def style():
    plt.rcParams.update({"figure.dpi": 120, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.edgecolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.labelcolor": INK, "font.size": 9, "legend.frameon": False,
                         "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
                         "lines.linewidth": 2})


def line(ax, x, y, cfg):
    ax.plot(x, y, color=COLORS[cfg], marker=MARKERS[cfg], markersize=6, label=LABEL[cfg],
            markeredgecolor="white", markeredgewidth=1)


def rho_mem(n):
    m = n.groupby(["carga", "config"]).mean(numeric_only=True)
    panels = [("s6_ttft", "S6 (k_R = 1) só TTFT", 100, "%"), ("ttft_p90", "TTFT p90", 1, "s"),
              ("espera_max", "espera máxima", 1, "s"), ("idle_ocio_politica", "ociosidade da política", 100, "pp")]
    fig, axs = plt.subplots(2, 4, figsize=(15, 6.6))
    for row, base in enumerate(("C1", "C6")):
        for ax, (col, title, sc, unit) in zip(axs[row], panels):
            for cfg in CONFIGS:
                line(ax, [10, 14, 19], [m.loc[(f"{base}n{k}", cfg)][col] * sc for k in (10, 14, 19)], cfg)
            ax.set_xticks([10, 14, 19], ["10\n(ρ 1,07)", "14\n(1,49)", "19\n(2,03)"])
            ax.set_title(f"{base}: {title} ({unit})")
            ax.set_ylim(bottom=0)
    axs[1, 0].set_xlabel("modelos de 8B (ρ_mem)")
    h, lab = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=5, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Varredura de ρ_mem: C1 (taxa por modelo fixa) e C6 (taxa total fixa); média de 3 repetições",
                 x=0.01, ha="left", fontsize=10.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(FIG / "fig_rho_mem.png", bbox_inches="tight")
    plt.close(fig)


def curves(c):
    c = c[~c.carga.isin(CONTROLS)]
    per = c.groupby(["carga", "config", "família", "k", "k_D"]).so_ttft.mean().reset_index()  # mean over reps
    avg = per.groupby(["config", "família", "k", "k_D"]).so_ttft.mean().reset_index()  # then over workloads
    fig, axs = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)
    for ax, (fam, xl, title) in zip(axs, (("S2", "k_T", "S2 só TTFT (base P95 dedicada)"),
                                          ("S6", "k_R", "S6 só TTFT (rotação sem preempção)"),
                                          ("S6P", "k_R", "S6P só TTFT (rotação com preempção)"))):
        for cfg in CONFIGS:
            g = avg[(avg["família"] == fam) & (avg.config == cfg) & (avg.k_D == 5)].sort_values("k")
            line(ax, g.k, g.so_ttft, cfg)
        ax.set_xscale("log")
        ks = sorted(set(avg[avg["família"] == fam].k))
        ax.set_xticks(ks, [f"{k:g}".replace(".", ",") for k in ks])
        ax.minorticks_off()
        ax.set_xlabel(xl)
        ax.set_title(title)
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    axs[0].set_ylabel("fração dentro do SLO (todas as enviadas)")
    h, lab = axs[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=5, bbox_to_anchor=(0.5, -0.06))
    fig.suptitle("Curvas de SLO, média das 16 cargas com disputa de residência (sem os controles C4 e C5)",
                 x=0.01, ha="left", fontsize=10.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG / "fig_curvas.png", bbox_inches="tight")
    plt.close(fig)


def violations(n):
    n = n[~n.carga.isin(CONTROLS)]
    per = n.groupby(["carga", "config"]).mean(numeric_only=True).groupby("config").mean()
    parts = [("s2_ttft", "dentro do SLO de TTFT", "#c9c8c3"),
             ("s2_inev_ativacao", "inevitável pela ativação", "#184f95"),
             ("s2_inev_rotacao", "inevitável pela rotação", "#2a78d6"),
             ("s2_evit_residencia", "evitável só com residência prévia", "#eda100"),
             ("s2_evit", "evitável", "#eb6834")]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    y = range(len(CONFIGS))
    left = [0.0] * len(CONFIGS)
    for col, lab, color in parts:
        vals = [per.loc[cfg][col] for cfg in CONFIGS]
        ax.barh(list(y), vals, left=left, color=color, label=lab, edgecolor="white", linewidth=2, height=0.62)
        for i, (l0, v) in enumerate(zip(left, vals)):
            if v >= 0.06:
                ax.text(l0 + v / 2, i, f"{v:.0%}", ha="center", va="center", fontsize=8,
                        color=INK if color in ("#c9c8c3", "#eda100") else "white")
        left = [a + b for a, b in zip(left, vals)]
    ax.set_yticks(list(y), [LABEL[c] for c in CONFIGS])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", ncol=3, bbox_to_anchor=(0.45, -0.42))
    ax.set_title("Requisições por resultado no TTFT, S2 (k_T = 10): média das 16 cargas com disputa (D43)")
    fig.tight_layout()
    fig.savefig(FIG / "fig_violacoes.png", bbox_inches="tight")
    plt.close(fig)


def idleness(n):
    n = n[~n.carga.isin(CONTROLS)]
    per = n.groupby(["carga", "config"]).mean(numeric_only=True).groupby("config").mean()
    fig, ax = plt.subplots(figsize=(9, 3.4))
    y = list(range(len(CONFIGS)))
    exp = [per.loc[c].idle_ocio_esperada for c in CONFIGS]
    pol = [per.loc[c].idle_ocio_politica for c in CONFIGS]
    ax.barh(y, exp, color="#c9c8c3", label="explicada pela carga (esperada)", edgecolor="white", linewidth=2,
            height=0.62)
    ax.barh(y, pol, left=exp, color="#2a78d6", label="da política (observada − esperada)", edgecolor="white",
            linewidth=2, height=0.62)
    for i, (e, p) in enumerate(zip(exp, pol)):
        ax.text(e + p + 0.01, i, f"{e + p:.0%} ({p:.0%} da política)", va="center", fontsize=8, color=INK2)
    ax.set_yticks(y, [LABEL[c] for c in CONFIGS])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", ncol=2, bbox_to_anchor=(0.45, -0.38))
    ax.set_title("Ociosidade da GPU (1 − utilização), média das 16 cargas com disputa (D44, D46)")
    fig.tight_layout()
    fig.savefig(FIG / "fig_ociosidade.png", bbox_inches="tight")
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    style()
    n = pd.read_csv(CAMP / "niveis.csv")
    c = pd.read_csv(CAMP / "curvas_niveis.csv")
    rho_mem(n)
    curves(c)
    violations(n)
    idleness(n)
    print(f"{FIG}: fig_rho_mem.png fig_curvas.png fig_violacoes.png fig_ociosidade.png")


if __name__ == "__main__":
    main()
