"""Plots for the ovl_* runs, from the compact data written by extract_ovl.py.

    import ovl_plots as op
    lv = op.nivel("reports/data/<run>/<config>/ovl_phases/rate0.5")
    op.linha_do_tempo(lv, "title", out="fig.png", fases=op.fases_por_modelo(lv))
    op.metricas(lv)  # one row of summary metrics

A level directory holds summary.json, requests.csv, gpu.csv, events.csv and its step's config.json one level up.
Times are seconds from the load start. Labels are in Portuguese (the reports are).
"""
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

COR = "#2a78d6"  # SGLang
TINTA, TINTA2, GRADE, JANELA, ERRO = "#0b0b0b", "#52514e", "#e4e3df", "#f1f0ec", "#e34948"
EV = {  # log events: color, marker, label
    "activate": ("#1baf7a", "^", "ativação pedida pelo controlador"),
    "evict": ("#6250d6", "v", "despejo por ociosidade"),
    "evict_pressure": ("#e87ba4", "v", "despejo sob pressão"),
    "evict_fair": ("#eda100", "v", "rodízio anti-fome (modelo ocupado)"),
    "evict_swap": ("#008300", "v", "troca por throughput/GB"),
    "kv_oom": (ERRO, "x", "kvcached sem memória (ativação falhou)"),
    "model_lost": ("#c98500", "X", "modelo perdido (ativação falhou ou worker morto)"),
    "kv_refused": ("#6da7ec", "|", "KV recusado pelo árbitro (sem queda)"),
    "oom": (ERRO, "X", "worker sem memória (torch OOM)"),
}
DESPEJOS = ("evict", "evict_pressure", "evict_fair", "evict_swap")
PESOS_8B_GB = 15.0

plt.rcParams.update({
    "figure.dpi": 110, "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": TINTA2, "axes.labelcolor": TINTA, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRADE, "grid.linewidth": 0.6, "xtick.color": TINTA2, "ytick.color": TINTA2,
    "font.size": 9.5, "legend.frameon": False, "legend.fontsize": 8.5, "lines.linewidth": 2,
})


def nivel(d):
    d = pathlib.Path(d)
    req = pd.read_csv(d / "requests.csv", dtype={"error": str, "model": str})
    req["fim"] = req.arrival + req.latency
    ev = pd.read_csv(d / "events.csv", dtype={"model": str, "value": str}).fillna({"model": "", "value": ""})
    return {"s": json.load(open(d / "summary.json")), "req": req, "gpu": pd.read_csv(d / "gpu.csv"), "ev": ev,
            "cfg": json.load(open(d.parent / "config.json")), "dir": d}


def eventos(lv, kind):
    return lv["ev"][lv["ev"].kind == kind]


def janela(ax, lv):
    ax.axvspan(0, lv["s"]["args"]["duration"], color=JANELA, zorder=0, lw=0)


def metricas(lv):
    s, req, ev = lv["s"], lv["req"], lv["ev"]
    dur = s["args"]["duration"]
    ok = req[req.status == "ok"]
    regime = ok[(ok.fim >= 0.25 * dur) & (ok.fim < dur)]
    k = ev.kind.value_counts()
    espera_1a = []  # per model: delay from its first request to its first response
    for m, r in req.groupby("model"):
        rok = r[r.status == "ok"]
        espera_1a.append((rok.fim.min() if len(rok) else np.inf) - r.arrival.min())
    return {
        "oferecido": s["offered_rps"], "em regime": len(regime) / (0.75 * dur),
        "atendidas": s["ok"], "enviadas": s["sent"], "não atendidas": s["unserved"], "falhas": s["failed"],
        "TTFT p50 (s)": s["ttft_p50"], "TTFT p90 (s)": float(np.nanpercentile(ok.ttft, 90)) if len(ok) else np.nan,
        "TTFT p99 (s)": s["ttft_p99"], "SLO": s["slo_attainment"], "GPU pico (GB)": lv["gpu"].used_gb.max(),
        "ativações": int(k.get("activate", 0)),
        "despejos ociosidade": int(k.get("evict", 0)), "despejos pressão": int(k.get("evict_pressure", 0)),
        "rodízios": int(k.get("evict_fair", 0)), "trocas throughput": int(k.get("evict_swap", 0)),
        "requisições preemptadas": int(pd.to_numeric(eventos(lv, "preempt").value).sum()),
        "ativações falhas (kvcached)": int(k.get("kv_oom", 0)),
        "falhas de driver kvcached": int(k.get("kv_oom", 0)), "torch OOM": int(k.get("oom", 0)),
        "KV recusado": int(k.get("kv_refused", 0)), "ativações revertidas": int(k.get("act_failed", 0)),
        "modelos perdidos": int(k.get("model_lost", 0)), "workers mortos": int(k.get("worker_dead", 0)),
        "pior 1ª resposta (s)": max(espera_1a) if espera_1a else np.nan,
    }


def fases_por_modelo(lv):
    a = lv["s"]["args"]
    ms, g, fase, dur = a["models"], a["groups"], a["phase"], a["duration"]
    if g <= 1:
        return None
    n = len(ms)
    out = {}
    for i in range(g):
        for m in ms[i * n // g:(i + 1) * n // g]:
            out[m] = [(k * fase, min((k + 1) * fase, dur)) for k in range(int(np.ceil(dur / fase))) if k % g == i]
    return out


def estados(lv, t0):
    # Intervals (start, end, state) per model, from the GPU scheduler's events.
    ev = lv["ev"]
    t_fim = max(lv["gpu"].t.max(), np.nanmax(lv["req"].fim.values))
    out = {}
    for m in lv["cfg"]:
        nome = m["model_name"]
        estado, desde, ints = ("ativo" if m["init_placements"][0]["on"] else "inativo"), t0, []
        e = ev[(ev.model == nome) & ev.kind.isin(["act_req", "act_ok", "deact_ok"])].sort_values("t")
        for t, kind in zip(e.t, e.kind):
            novo = {"act_req": "ativando", "act_ok": "ativo", "deact_ok": "inativo"}[kind]
            if novo != estado:
                ints.append((max(desde, t0), t, estado))
                estado, desde = novo, t
        ints.append((max(desde, t0), t_fim, estado))
        out[nome] = ints
    return out


def linha_do_tempo(lv, titulo, out=None, xlim=None, fases=None):
    """GPU memory, free memory seen by the global controller, and each model's state and responses."""
    modelos = [m["model_name"] for m in lv["cfg"]]
    req, gpu, ev = lv["req"], lv["gpu"], lv["ev"]
    x0 = xlim[0] if xlim else -15
    alturas = [1.1, 0.9, 0.32 * len(modelos) + 0.4]
    fig, axs = plt.subplots(3, 1, sharex=True, figsize=(11, 1.9 * sum(alturas)), gridspec_kw={"height_ratios": alturas})
    ax = axs[0]
    janela(ax, lv)
    ax.plot(gpu.t, gpu.used_gb, color=COR)
    total = gpu.total_gb.iloc[0]
    ax.axhline(total, color=TINTA2, ls="--", lw=1)
    ax.text(x0, total, f" total {total:.1f} GB", va="bottom", color=TINTA2, fontsize=8)
    for kind in ("activate",) + DESPEJOS + ("kv_oom", "oom", "model_lost"):
        for t in eventos(lv, kind).t:
            ax.axvline(t, color=EV[kind][0], lw=1, alpha=0.8)
    ax.set_ylabel("GB usados")
    ax.set_ylim(0, total * 1.12)
    ax.set_title("Memória da GPU (nvidia-smi); linhas verticais = eventos da legenda")
    ax = axs[1]
    janela(ax, lv)
    fm = eventos(lv, "free_mem")
    ax.step(fm.t, fm.value.astype(float), where="post", color=TINTA2, lw=1.5)
    ax.axhline(PESOS_8B_GB, color=EV["activate"][0], ls=":", lw=1.2)
    ax.text(x0, PESOS_8B_GB, " pesos de um 8B (15 GB)", va="bottom", color=TINTA2, fontsize=8)
    for t in eventos(lv, "activate").t:
        antes = fm[fm.t <= t + 0.01].value.astype(float)
        if len(antes):
            ax.plot(t, antes.iloc[-1], marker="^", color=EV["activate"][0], ms=8, mec="white", mew=1.5)
    ax.set_ylabel("GB livres")
    ax.set_title("Memória livre que o controlador global viu em cada ciclo (base da decisão de ativar)")
    ax = axs[2]
    janela(ax, lv)
    est = estados(lv, x0)
    for y, m in enumerate(modelos):
        if fases:
            for a, b in fases.get(m, []):
                ax.axvspan(a, b, ymin=1 - (y + 1) / len(modelos), ymax=1 - y / len(modelos), color="#dcdad3",
                           lw=0, zorder=0.5)
        for a, b, st in est[m]:
            if st == "ativo":
                ax.barh(y, b - a, left=a, height=0.62, color=COR, alpha=0.28, lw=0, zorder=1)
            elif st == "ativando":
                ax.barh(y, b - a, left=a, height=0.62, facecolor="none", edgecolor="#c98500", hatch="////",
                        lw=0.8, zorder=1)
        r = req[req.model == m]
        ok, nao, falha = r[r.status == "ok"], r[r.status == "unserved"], r[r.status == "failed"]
        ax.plot(ok.fim, np.full(len(ok), y), "|", color=TINTA, ms=7, alpha=0.55, zorder=2)
        ax.plot(nao.arrival, np.full(len(nao), y + 0.22), "x", color=ERRO, ms=3.5, mew=0.9, zorder=2)
        ax.plot(falha.arrival, np.full(len(falha), y - 0.22), ".", color=ERRO, ms=3, zorder=2)
        for kind in ("activate",) + DESPEJOS + ("model_lost",):
            e = ev[(ev.kind == kind) & (ev.model == m)]
            ax.plot(e.t, np.full(len(e), y), EV[kind][1], color=EV[kind][0], ms=8, mec="white", mew=1.2, zorder=3)
    ax.set_yticks(range(len(modelos)), modelos)
    ax.set_ylim(len(modelos) - 0.4, -0.6)
    ax.grid(axis="y", visible=False)
    ax.set_title("Estado de cada modelo e respostas recebidas")
    ax.set_xlabel("tempo desde o início da carga (s)")
    ax.set_xlim(*(xlim or (x0, None)))
    alca = [Patch(color=COR, alpha=0.28, label="ativo"),
            Patch(facecolor="none", edgecolor="#c98500", hatch="////", label="ativando (pedido sem conclusão)"),
            Line2D([], [], marker="|", ls="", color=TINTA, ms=8, label="resposta concluída"),
            Line2D([], [], marker="x", ls="", color=ERRO, label="chegada não atendida")]
    if len(req[req.status == "failed"]):
        alca.append(Line2D([], [], marker=".", ls="", color=ERRO, label="chegada que falhou"))
    if fases:
        alca.append(Patch(color="#dcdad3", label="grupo do modelo recebendo carga"))
    alca += [Line2D([], [], marker=EV[k][1], ls="", color=EV[k][0], ms=7, label=EV[k][2])
             for k in ("activate",) + DESPEJOS + ("kv_oom", "oom", "model_lost") if len(eventos(lv, k))]
    alca.append(Patch(color=JANELA, label="janela de carga"))
    fig.legend(handles=alca, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(titulo, x=0.01, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    if out:
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
    return fig
