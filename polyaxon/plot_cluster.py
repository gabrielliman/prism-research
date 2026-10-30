"""Figures for the node-variation report (reports/2026-10-30 Variação de desempenho do nó do cluster.md).

Usage: python3 polyaxon/plot_cluster.py <history.csv> <probes.csv> <out dir>

<history.csv> is polyaxon/cluster_history.py's output; <probes.csv> is polyaxon/cluster_probe_summary.py's.
Writes:
  mesmo_codigo.png   same code (2ac0098 and the current tree with the new flags off), same workloads, 10-29 vs 10-30:
                     median TPOT and SLO per run
  historico.png      10-21..10-30 timeline: TPOT relative to the median of the same workload, kvcached start-up
                     time, and levels that failed (kvcached driver error / model service crash / dead worker)
  concorrencia.png   share of levels with a kvcached driver error / model service death by number of Prism jobs
                     running on the node at the same time (prism_jobs_on_node)
  sondas.png         probe series: each benchmark as % difference from the idle-node baseline, and node load average
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BLUE, RED, INK, MUTED, GRID = "#2a78d6", "#e34948", "#0b0b0b", "#52514e", "#e6e5e0"
ALIAS = {("ovl_phases", "rate0.5"): {"A0.1": ["idle50", "base", "base_phases", "A0.1_phases", "original", "phases_idle50"],
                                     "A0.2": ["idle10", "A0.2_phases"]},
         ("ovl_trace_big", "ts1"): {"A0.3": ["tp_P0D1", "A0.3_trace12", "A0.3_plain", "A0.3_instr", "tp_P0D1_trace"]}}
SAME_CODE_JOBS = ("f0-repro", "f1-repro", "f1-code", "f1-ab")  # 2ac0098, or the current tree with the F1 flags off


def style(ax):
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)


def load_history(path):
    d = pd.read_csv(path)
    for k in ("t_start_utc", "t_end_utc"):
        d[k] = pd.to_datetime(d[k], utc=True, format="mixed")
    d = d.dropna(subset=["t_start_utc", "t_end_utc"])
    d = d[~d.job.str.startswith("vllm")].copy()

    def canon(r):
        for k, v in ALIAS.get((r.step, r.level), {}).items():
            if r.config in v:
                return k
        return r.config

    d["wl"] = d.step + "/" + d.level + "/" + d.apply(canon, axis=1)
    d["mid"] = d.t_start_utc + (d.t_end_utc - d.t_start_utc) / 2
    d["fail"] = (d.kvc_driver_err.fillna(0) > 0) | (d.model_service_crash.fillna(0) > 0) | (d.dead_workers.fillna(0) > 0)
    med = d[~d.fail].groupby("wl").tpot_med_ms.median()
    d["tpot_idx"] = d.tpot_med_ms / d.wl.map(med)
    d["n_wl"] = d.groupby("wl").tpot_med_ms.transform("count")
    return d


def fig_same_code(d, out):
    s = d[d.job.str.startswith(SAME_CODE_JOBS) & ~d.fail & d.wl.isin(
        ["ovl_phases/rate0.5/A0.1", "ovl_phases/rate0.5/A0.2", "ovl_trace_big/ts1/A0.3"])].copy()
    s["day"] = s.mid.dt.strftime("%d/%m")
    names = {"ovl_phases/rate0.5/A0.1": "A0.1 (ovl_phases, ociosidade 50 s)",
             "ovl_phases/rate0.5/A0.2": "A0.2 (ovl_phases, ociosidade 10 s)",
             "ovl_trace_big/ts1/A0.3": "A0.3 (ovl_trace_big, troca P0D1)"}
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.6))
    rng = np.random.default_rng(0)
    for j, wl in enumerate(names):
        x = s[s.wl == wl]
        days = sorted(x.day.unique(), key=lambda v: (v[3:], v[:2]))
        for i, (col, lab) in enumerate([("tpot_med_ms", "TPOT mediano (ms)"), ("slo_pct", "SLO S1 (%)")]):
            ax = axes[i, j]
            for k, dy in enumerate(days):
                v = x[x.day == dy][col].values
                ax.scatter(k + rng.uniform(-0.12, 0.12, len(v)), v, s=36, color=BLUE, edgecolor="white", lw=1.2, zorder=3)
                ax.hlines(np.median(v), k - 0.25, k + 0.25, color=INK, lw=2, zorder=4)
                ax.annotate(f"{np.median(v):.1f}", (k + 0.28, np.median(v)), va="center", fontsize=8, color=INK)
            ax.set_xticks(range(len(days)), [f"{dy}\n({(x.day == dy).sum()} exec.)" for dy in days])
            ax.set_xlim(-0.6, len(days) - 0.2)
            style(ax)
            if j == 0:
                ax.set_ylabel(lab, fontsize=9, color=INK)
            if i == 0:
                ax.set_title(names[wl], fontsize=9.5, color=INK, loc="left")
    fig.suptitle("Mesmo código, mesma carga e mesmas sementes: 29/10 × 30/10 (pontos = execuções; traço = mediana)",
                 fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_history(d, out):
    k = d[d.n_wl >= 3]
    fig, axes = plt.subplots(3, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.2]})
    ax = axes[0]
    ok = k[~k.fail]
    ax.scatter(ok.mid, ok.tpot_idx, s=14, color=BLUE, alpha=0.75, edgecolor="none", label="nível limpo")
    ax.axhline(1, color=MUTED, lw=1, ls="--")
    ax.set_ylabel("TPOT / mediana da\nmesma carga", fontsize=9, color=INK)
    ax.set_ylim(0.6, 1.8)
    style(ax)
    ax = axes[1]
    h = d.dropna(subset=["kvc_init_s"])
    ax.scatter(h.mid, h.kvc_init_s, s=14, color=BLUE, alpha=0.75, edgecolor="none")
    ax.set_ylabel("partida do kvcached,\n10 processos (s)", fontsize=9, color=INK)
    style(ax)
    ax = axes[2]
    f = d[d.fail]
    env = f[(f.mid >= "2026-10-27") & ~f.job.str.startswith("limits-base")]
    other = f.drop(env.index)
    ax.scatter(other.mid, np.zeros(len(other)), marker="|", s=120, color=MUTED, lw=1.5,
               label="falha com código antigo ou teste de limite de memória")
    ax.scatter(env.mid, np.zeros(len(env)), marker="|", s=120, color=RED, lw=1.5,
               label="falha ambiental (erro de driver do kvcached / model service morto)")
    ax.set_yticks([])
    ax.set_ylim(-1, 1)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=2, bbox_to_anchor=(0, 1.6))
    style(ax)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.suptitle("Histórico 21/10–30/10 (UTC): velocidade de decode relativa, partida do kvcached e falhas por nível",
                 fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_concurrency(d, out):
    e = d[(d.mid >= "2026-10-27") & ~d.job.str.startswith("limits-base")].dropna(subset=["prism_jobs_on_node"]).copy()
    e["n"] = e.prism_jobs_on_node.astype(int).clip(upper=6)
    e["k1"] = e.kvc_driver_err.fillna(0) > 0
    e["ms"] = e.model_service_crash.fillna(0) > 0
    g = e.groupby("n").agg(levels=("k1", "size"), k1=("k1", "sum"), ms=("ms", "sum")).reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, col, title in [(axes[0], "k1", "níveis com erro de driver do kvcached (cuMemSetAccess/cuMemCreate OOM)"),
                           (axes[1], "ms", "níveis em que o model service morreu (CUDA OOM)")]:
        pct = 100 * g[col] / g.levels
        ax.bar(g.n, pct, width=0.6, color=BLUE, edgecolor="white", linewidth=2)
        for x, y, k, n in zip(g.n, pct, g[col], g.levels):
            ax.annotate(f"{k}/{n}", (x, y), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8, color=INK)
        ax.set_xticks(g.n, [str(v) if v < 6 else "6+" for v in g.n])
        ax.set_xlabel("jobs Prism rodando no nó ao mesmo tempo", fontsize=9, color=INK)
        ax.set_ylabel("% dos níveis", fontsize=9, color=INK)
        ax.set_ylim(0, 112)
        ax.set_title(title, fontsize=9, color=INK, loc="left")
        style(ax)
    fig.suptitle("Falhas de driver por número de jobs Prism simultâneos no nó (27/10–30/10, código com as correções)",
                 fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_probes(p, out):
    """Each metric as % difference from the idle-node baseline (median of probes with load average < 2), all on the
    same fixed ±15% scale so small and large effects read the same; node load average in its own panel."""
    p = p.copy()
    p["t"] = pd.to_datetime(p.start_utc, utc=True)
    p = p.sort_values("t")
    idle = p[p.load1_max < 2]
    panels = [("launch_us", "lançamento de kernel"), ("decode_b1_ms", "decode lote 1, eager"),
              ("decode_b1_graph_ms", "decode lote 1, CUDA graph"), ("decode_b32_ms", "decode lote 32"),
              ("matmul_tflops", "matmul bf16"), ("h2d_pinned_gbs", "cópia host → GPU")]
    fig, axes = plt.subplots(len(panels) + 1, 1, figsize=(11, 1.25 * len(panels) + 2.6), sharex=True)
    under = p.probe.str.contains("underload")
    for ax, (col, lab) in zip(axes, panels):
        base = idle[col].median()
        pct = 100 * (p[col] / base - 1)
        ax.axhspan(-5, 5, color=GRID, alpha=0.6, lw=0)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.plot(p.t[~under], pct[~under], "-o", color=BLUE, ms=4, lw=1.5)
        ax.scatter(p.t[under], pct[under], s=40, color=RED, zorder=4)
        ax.set_ylim(-15, 15)
        ax.set_yticks([-10, 0, 10])
        ax.set_ylabel(f"{lab}\n(base {base:.3g})", fontsize=8, color=INK, rotation=0, ha="right", va="center")
        style(ax)
    ax = axes[-1]
    ax.plot(p.t[~under], p.load1_max[~under], "-o", color=BLUE, ms=4, lw=1.5, label="série periódica")
    ax.scatter(p.t[under], p.load1_max[under], s=40, color=RED, zorder=4, label="durante 4 jobs Prism simultâneos")
    ax.set_ylabel("load average\ndo nó (128 CPUs)", fontsize=8, color=INK, rotation=0, ha="right", va="center")
    style(ax)
    ax.legend(fontsize=8, frameon=False, loc="upper left", ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    fig.suptitle("Sondas padronizadas: diferença em % para o nó ocioso (faixa cinza = ±5%)", fontsize=10.5,
                 color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main():
    hist, probes, out = sys.argv[1:4]
    d = load_history(hist)
    fig_same_code(d, f"{out}/mesmo_codigo.png")
    fig_history(d, f"{out}/historico.png")
    fig_concurrency(d, f"{out}/concorrencia.png")
    try:
        p = pd.read_csv(probes)
        if len(p):
            fig_probes(p, f"{out}/sondas.png")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
