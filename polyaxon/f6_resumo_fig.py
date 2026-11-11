"""F6 phase report figure: total within the deadline (TTFT only) x worst quarter of models, one panel per deadline level,
F6.15 means over the 20 jobs (4 workloads x 5 reps). Colours keep the F6.0 figure's mapping (dataviz default categorical
slots, fixed order); hollow = with preemption.

Usage: f6_resumo_fig.py <F6.15 analysis dir> <out.png>   (reads tabela_politicas.csv from f615_compare.py)
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

t = pd.read_csv(sys.argv[1].rstrip("/") + "/tabela_politicas.csv")
t = t[t.carga == "todas"]
# policy -> (label, colour, hollow)
POL = {"A0.2+A1 idle eviction 10 s": ("ociosidade 10 s (A0.2+A1)", "#2a78d6", False),
       "A0.4 throughput swap": ("troca por throughput (A0.4)", "#eb6834", False),
       "A2.1 EDF": ("EDF (A2.1)", "#1baf7a", False),
       "A2.1 EDF + preemption": ("EDF com preempção", "#1baf7a", True),
       "A9.4 VLT per-swap preempt (lambda 1)": ("VLT, preempção por troca (A9.4)", "#eda100", False),
       "A9.2 VLT residency": ("VLT ciente da residência (A9.2)", "#e87ba4", False)}
LV = {"S3k5": "prazo de 5× a ativação (~7 s)", "S6k1": "prazo de 1 troca (~16 s)",
      "S6k2": "prazo de 2 trocas (~31 s)", "S6k4": "prazo de 4 trocas (~63 s)"}
INK, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"

fig, axes = plt.subplots(1, 4, figsize=(16, 4.6), sharey=True)
for ax, lv in zip(axes, LV):
    for pol, (lab, col, hollow) in POL.items():
        x = t[(t.nivel == lv) & (t.politica == pol)]
        if x.empty:
            continue
        ax.scatter(x["total %"], x["worst quarter %"], s=80, facecolors="none" if hollow else col, edgecolors=col,
                   linewidths=2, zorder=3)
        if pol.startswith("A0.2"):  # the point of the figure: high total, starved models
            ax.annotate("ociosidade 10 s", (x["total %"].iloc[0], x["worst quarter %"].iloc[0]),
                        textcoords="offset points", xytext=(-8, 8), ha="right", fontsize=8, color=MUTED)
    ax.set_title(LV[lv], fontsize=10, color=INK)
    ax.set_xlabel("total no prazo do 1º token (%)", fontsize=9, color=MUTED)
    ax.margins(x=0.15, y=0.1)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_facecolor(SURF)
axes[0].set_ylabel("pior quarto dos modelos no prazo (%)", fontsize=9, color=MUTED)
fig.suptitle("F6.15: total × pior quarto dos modelos (média de 20 jobs: 4 cargas × 5 repetições); "
             "cheio = sem preempção, vazado = com", fontsize=10, color=INK)
handles = [Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor="none" if h else c,
                  markeredgecolor=c, markeredgewidth=2, label=l) for l, c, h in POL.values()]
fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=8.5, labelcolor=MUTED)
fig.patch.set_facecolor(SURF)
fig.tight_layout(rect=(0, 0.08, 1, 1))
fig.savefig(sys.argv[2], dpi=150)
print(sys.argv[2])
