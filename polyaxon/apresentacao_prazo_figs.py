"""Figures for the presentation on the first round of deadline-based policies (2026-11-05).

Usage:
    PY=/mnt/scratch/scheduler/opt-env/bin/python
    $PY polyaxon/apresentacao_prazo_figs.py reports/data/F06a/triagem reports/data/F06a/apresentacao \
        reports/figs/2026-11-05-prazo

Inputs:
    <triagem>/niveis.csv, <triagem>/pareado.csv   written by polyaxon/f6a_triage.py
    <apresentacao>/linha_do_tempo/<config>/       extract_ovl.py output for job t1-2b (21f31370):
                                                  A0.1, edf_S3k5, lvf_S3k5
Labels are descriptive (the audience does not know the internal A*/C*/S* names).
"""
import glob
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ovl_plots as op  # noqa: E402

TINTA, TINTA2, GRADE = "#0b0b0b", "#52514e", "#e4e3df"
AZUL, LARANJA, AGUA, AMARELO, CINZA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#9a9893"
plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": TINTA2, "axes.labelcolor": TINTA, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.6, "xtick.color": TINTA2, "ytick.color": TINTA2,
    "legend.frameon": False, "figure.dpi": 130, "savefig.bbox": "tight",
})

CARGA = {"ovl_mem": "Todos sempre ativos (10 modelos, memória para 6)", "ovl_trace_big": "Trace real (12 modelos)"}
CARGA_CURTA = {"ovl_mem": "todos sempre ativos", "ovl_trace_big": "trace real"}
SLO = {"S2k10": "TTFT ≤ 10× o p95 isolado", "S2k25": "TTFT ≤ 25× o p95 isolado", "S3k5": "TTFT ≤ 5× a ativação"}
SPEC = {"S2k10": "S2:kT=10,kD=5", "S2k25": "S2:kT=25,kD=5", "S3k5": "S3:kA=5,kD=5"}


def nome_politica(cfg):
    pol, slo = cfg.split("_", 1)
    ciclo = ", ciclo 1 s" if pol.endswith("1s") else ""
    return f"{'EDF' if pol.startswith('edf') else 'VLT'} · {SLO[slo]}{ciclo}"


def fig_slos(dest):
    """Deadlines against the model's isolated latency and the activation cost (log scale)."""
    linhas = [  # label, seconds, role
        ("TTFT isolado, p50", 0.0353, "iso"),
        ("TTFT isolado, p95", 0.0698, "iso"),
        ("Prazo: 10× o p95 isolado", 0.70, "slo"),
        ("Prazo absoluto do Prism (1 s)", 1.0, "slo"),
        ("Ativação estimada (mediana)", 1.4, "at"),
        ("Prazo: 25× o p95 isolado", 1.75, "slo"),
        ("Ativação medida sob carga (mediana)", 5.4, "at"),
        ("Prazo: 5× a ativação estimada", 7.0, "slo"),
        ("Rotação completa medida (mediana, EDF)", 16.8, "at"),
    ]
    cor = {"iso": CINZA, "slo": AZUL, "at": LARANJA}
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for y, (lab, v, papel) in enumerate(linhas[::-1]):
        ax.barh(y, v, color=cor[papel], height=0.55)
        ax.text(v * 1.08, y, f"{v * 1000:.0f} ms" if v < 1 else f"{v:.2f} s".replace(".", ","), va="center",
                color=TINTA, fontsize=9)
    ax.set_yticks(range(len(linhas)), [l[0] for l in linhas[::-1]])
    ax.set_xscale("log")
    ax.set_xlim(0.02, 60)
    ax.set_xlabel("segundos (escala log)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Prazos de TTFT × latência isolada × custo de colocar um modelo na GPU (Llama-3.1-8B)")
    ax.text(0, -0.17, "Isolado e prazos: carga 'todos sempre ativos' (no trace real: 25/64 ms, prazos 0,64 e 1,61 s). "
            "Ativação e rotação medidas: trace real, 1 execução.", transform=ax.transAxes, fontsize=7.5, color=TINTA2)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=CINZA, label="modelo sozinho na GPU"), Patch(color=AZUL, label="prazo testado"),
                       Patch(color=LARANJA, label="custo de ativação / rotação")], loc="upper right", fontsize=9)
    fig.savefig(dest / "slos_vs_isolado.png")
    plt.close(fig)


def _rotacoes(d):
    ev = pd.read_csv(glob.glob(f"{d}/*/*/events.csv")[0], dtype={"model": str, "value": str})
    ativ = []
    for _, g in ev[ev.kind.isin(["act_req", "act_ok"])].sort_values("t").groupby("model"):
        ult = None
        for _, e in g.iterrows():
            if e.kind == "act_req":
                ult = e.t
            elif ult is not None:
                ativ.append(e.t - ult)
                ult = None
    rot = []
    for _, e in ev[ev.kind.isin(["evict_edf", "evict_lvf"])].iterrows():
        ok = ev[(ev.kind == "act_ok") & (ev.model == e.value) & (ev.t >= e.t)]
        if len(ok):
            rot.append(ok.t.iloc[0] - e.t)
    return np.array(ativ), np.array(rot)


def fig_rotacao(tl, dest):
    """Measured activation and full-rotation times against the tested deadlines (1 run, trace real)."""
    a0, _ = _rotacoes(tl / "A0.1")
    ae, re_ = _rotacoes(tl / "edf_S3k5")
    al, rl = _rotacoes(tl / "lvf_S3k5")
    linhas = [("ativação (pedido → pronto)\nPrism original", a0), ("ativação (pedido → pronto)\nEDF", ae),
              ("ativação (pedido → pronto)\nVLT", al), ("rotação (decisão → modelo pronto)\nEDF", re_),
              ("rotação (decisão → modelo pronto)\nVLT", rl)]
    fig, ax = plt.subplots(figsize=(9, 3.9))
    rng = np.random.default_rng(0)
    for y, (lab, v) in enumerate(linhas[::-1]):
        cor = LARANJA if "rotação" in lab else AZUL
        ax.scatter(v, y + rng.uniform(-0.18, 0.18, len(v)), s=16, color=cor, alpha=0.55, lw=0)
        med = np.median(v)
        ax.plot([med, med], [y - 0.3, y + 0.3], color=TINTA, lw=2)
        ax.text(med, y + 0.34, f"mediana {med:.1f} s (n={len(v)})".replace(".", ","), ha="center", fontsize=8,
                color=TINTA)
    for p, lab in ((0.70, "10× isolado"), (1.75, "25× isolado"), (7.0, "5× ativação")):
        ax.axvline(p, color=TINTA2, ls="--", lw=1)
        ax.text(p, -0.85, f"prazo\n{lab}", va="center", ha="center", fontsize=7.5, color=TINTA2,
                bbox=dict(facecolor="white", edgecolor="none", pad=1))
    ax.set_ylim(-1.2, len(linhas) - 0.3)
    ax.set_yticks(range(len(linhas)), [l[0] for l in linhas[::-1]], fontsize=8.5)
    ax.set_xscale("log")
    ax.set_xlim(0.4, 200)
    ax.set_xlabel("segundos (escala log)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Quanto uma troca de modelo leva de fato (trace real, prazo 5× ativação, 1 execução)")
    fig.savefig(dest / "custo_real_da_troca.png")
    plt.close(fig)


def fig_pareado(par, dest):
    """Paired difference against the best of the two idle-threshold baselines, same job."""
    p = par[(par.vista == "comb") & (par.versao != "v1")].copy()
    ordem = ["edf_S2k10", "edf_S2k25", "edf_S3k5", "edf1s_S2k10", "edf1s_S2k25",
             "lvf_S2k10", "lvf_S2k25", "lvf_S3k5", "lvf1s_S3k5"]
    ordem = [o for o in ordem if o in set(p.config)]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.axvspan(-8, 8, color="#f1f0ec", lw=0, zorder=0)
    ax.axvline(0, color=TINTA2, lw=1)
    for k, (cen, cor) in enumerate((("ovl_mem", AZUL), ("ovl_trace_big", LARANJA))):
        for y, cfg in enumerate(ordem[::-1]):
            v = p[(p.cenário == cen) & (p.config == cfg)].dif_pp
            if not len(v):
                continue
            yy = y + (0.15 if k == 0 else -0.15)
            ax.scatter(v, [yy] * len(v), s=22, facecolor="white", edgecolor=cor, lw=1.2, zorder=3)
            ax.scatter([v.mean()], [yy], s=60, color=cor, zorder=4, label=CARGA[cen] if y == 0 else None)
    ax.set_yticks(range(len(ordem)), [nome_politica(o) for o in ordem[::-1]], fontsize=8.5)
    ax.set_xlabel("diferença no SLO combinado (pontos percentuais), contra a melhor linha de base do mesmo job")
    ax.text(0, len(ordem) - 0.45, "faixa ±8 pontos (sinal mínimo)", ha="center", fontsize=8, color=TINTA2)
    ax.set_ylim(-0.6, len(ordem) - 0.3)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.4, -0.12), ncol=2, fontsize=8.5)
    ax.set_title("Nenhuma configuração ganhou: diferença pareada (ponto cheio = média; vazios = repetições)")
    fig.savefig(dest / "diferenca_pareada.png")
    plt.close(fig)


def _media(niv, cen, cfg, spec, jobs=None):
    d = niv[(niv.cenário == cen) & (niv.config == cfg) & (niv.slo == spec)]
    if jobs is not None:
        d = d[d.job.isin(jobs)]
    return d.mean(numeric_only=True)


def fig_violacoes(niv, dest):
    """Where the requests go: met, TTFT avoidable, TTFT unavoidable, TPOT only."""
    edf_c1 = ["edf2-c1-1", "edf2-c1-2"]
    edf_t1 = ["t1-2b", "edf2-t1-1"]
    casos = [
        ("ovl_mem", "S2k10", "A0.1", "Prism original", None), ("ovl_mem", "S2k10", "edf_S2k10", "EDF", edf_c1),
        ("ovl_mem", "S2k10", "lvf_S2k10", "VLT", None),
        ("ovl_trace_big", "S2k10", "A0.1", "Prism original", None),
        ("ovl_trace_big", "S2k10", "edf_S2k10", "EDF", edf_t1), ("ovl_trace_big", "S2k10", "lvf_S2k10", "VLT", None),
        ("ovl_trace_big", "S3k5", "A0.1", "Prism original", None),
        ("ovl_trace_big", "S3k5", "edf_S3k5", "EDF", edf_t1), ("ovl_trace_big", "S3k5", "lvf_S3k5", "VLT", None),
    ]
    cats = [("ambos_ok", "cumpre TTFT e TPOT", AZUL), ("viol_ttft_evitavel", "viola TTFT, evitável", LARANJA),
            ("viol_ttft_inevitavel", "viola TTFT, inevitável (prazo < ativação)", AGUA),
            ("viola_so_tpot", "viola só TPOT", AMARELO)]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    labs = []
    for y, (cen, s, cfg, nome, jobs) in enumerate(casos[::-1]):
        m = _media(niv, cen, cfg, SPEC[s], jobs)
        x = 0
        for col, _, cor in cats:
            w = 100 * m[col]
            ax.barh(y, w, left=x, color=cor, height=0.6, edgecolor="white", lw=1.5)
            if w >= 6:
                ax.text(x + w / 2, y, f"{w:.0f}", ha="center", va="center", fontsize=8, color="white")
            x += w
        labs.append(f"{nome} · {CARGA_CURTA[cen]} · {SLO[s]}")
    ax.set_yticks(range(len(casos)), labs, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% das requisições enviadas")
    ax.grid(axis="y", visible=False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=l) for _, l, c in cats], ncol=2, fontsize=8,
              loc="upper center", bbox_to_anchor=(0.45, -0.13))
    ax.set_title("As políticas não reduzem as violações inevitáveis e criam violações evitáveis")
    fig.savefig(dest / "violacoes_evitaveis.png")
    plt.close(fig)


def fig_rotacoes(niv, par, dest):
    """More rotations, lower SLO: every rotating policy against the best idle-threshold baseline."""
    pts = []
    p = par[(par.vista == "comb") & (par.versao != "v1")]
    r = par[(par.vista == "rotacoes_min") & (par.versao != "v1")]
    for _, row in p.iterrows():
        rr = r[(r.job == row.job) & (r.config == row.config) & (r.slo == row.slo)]
        pts.append(("EDF" if row.config.startswith("edf") else "VLT", row.cenário, rr.valor.iloc[0], row.dif_pp))
    for job in ("c1-1", "c1-2", "t1-1", "t1-2b"):
        for s in SPEC.values():
            d = niv[(niv.job == job) & (niv.slo == s)]
            base = d[d.config.isin(["A0.1", "A0.2"])].comb.max()
            for cfg in ("A0.3", "fair"):
                x = d[d.config == cfg]
                if len(x):
                    pts.append(("linhas de base com rodízio", x.cenário.iloc[0], x.rotacoes_min.iloc[0],
                                100 * (x.comb.iloc[0] - base)))
    df = pd.DataFrame(pts, columns=["serie", "cen", "rot", "dif"])
    fig, ax = plt.subplots(figsize=(8, 4.4))
    ax.axhspan(-8, 8, color="#f1f0ec", lw=0, zorder=0)
    ax.axhline(0, color=TINTA2, lw=1)
    for serie, cor in (("linhas de base com rodízio", AGUA), ("EDF", AZUL), ("VLT", LARANJA)):
        for cen, mk in (("ovl_mem", "o"), ("ovl_trace_big", "^")):
            d = df[(df.serie == serie) & (df.cen == cen)]
            ax.scatter(d.rot, d.dif, color=cor, marker=mk, s=42, edgecolor="white", lw=1.2, zorder=3,
                       label=f"{serie} · {CARGA_CURTA[cen]}")
    ax.set_xlabel("rotações por minuto (modelo retirado para dar lugar a outro)")
    ax.set_ylabel("diferença no SLO combinado (pp)\ncontra a melhor linha de base sem rodízio")
    ax.legend(fontsize=7.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    ax.set_title("Rodízio custa caro: só fica perto de 0 a EDF no trace real, que tirava modelos ociosos")
    fig.savefig(dest / "rotacoes_vs_slo.png")
    plt.close(fig)


def fig_linhas_do_tempo(tl, dest):
    op.EV["evict_edf"] = (op.EV["evict_edf"][0], "v", "rotação por folga (EDF)")
    op.EV["evict_lvf"] = (op.EV["evict_lvf"][0], "v", "rotação por atraso virtual (VLT)")
    for cfg, nome in (("A0.1", "Prism original (ociosidade de 50 s)"), ("edf_S3k5", "EDF, prazo 5× a ativação")):
        lv = op.nivel(next((tl / cfg).glob("*/ts1")))
        op.linha_do_tempo(lv, f"Trace real, 12 modelos: {nome}", out=dest / f"linha_do_tempo_{cfg}.png")


def main():
    tri, apr, dest = map(pathlib.Path, sys.argv[1:4])
    dest.mkdir(parents=True, exist_ok=True)
    niv, par = pd.read_csv(tri / "niveis.csv"), pd.read_csv(tri / "pareado.csv")
    tl = apr / "linha_do_tempo"
    fig_slos(dest)
    fig_rotacao(tl, dest)
    fig_pareado(par, dest)
    fig_violacoes(niv, dest)
    fig_rotacoes(niv, par, dest)
    fig_linhas_do_tempo(tl, dest)
    print("figuras em", dest)


if __name__ == "__main__":
    main()
