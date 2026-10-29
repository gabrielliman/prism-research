"""Figures for the load-limit report: for each axis, where each error shows up, base vs current code.

Usage: python3 polyaxon/plot_limits.py <errors.csv from classify_errors.py> <figs dir>

One figure per axis (limits_<axis>_suite.tsv): rows = errors, columns = load levels, one panel per version.
A cell is dark when the error showed up in at least one repetition; the text is "<reps with it>/<reps>" and,
below the grid, the share of requests served. Needs pandas and matplotlib.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

AXES = {  # axis -> (title, suites, x label from the row)
    "A": ("Eixo A: demanda com rodízio (ovl_mem, 10 × 8B, 6 ativos)", ["mem_rate"], lambda r: r.level.replace("rate", "") + " req/s"),
    "B": ("Eixo B: número de modelos (ovl_mem a 0,2 req/s, 6 ativos)", ["n06", "n08", "n10", "n12", "n14"], lambda r: f"{int(r.suite[1:])} modelos"),
    "C": ("Eixo C: crescimento do KV (ovl_kv, 4 × 8B ativos)", ["kv_rate"], lambda r: r.level.replace("rate", "") + " req/s"),
    "D": ("Eixo D: troca de grupos (ovl_phases, 10 × 8B)", ["phases_rate"], lambda r: r.level.replace("rate", "") + " req/s"),
}
ERRORS = [  # (id, label, condition on one level row)
    ("F5", "servidor não sobe", lambda r: r.start_failed > 0),
    ("P1", "ativação sem espaço (conta dupla)", lambda r: r.act_overcommit > 0),
    ("K1", "abort do kvcached (cuMem)", lambda r: r.k1 > 0),
    ("P3/S3", "torch OOM na ativação", lambda r: r.oom_act > 0),
    ("—", "torch OOM no forward", lambda r: r.oom_fwd > 0),
    ("S1", "pretty_print (KV cheio no prefill)", lambda r: r.pretty_print > 0),
    ("S2", "servidor caiu", lambda r: r.failed_conn > 0),
    ("S4", "término vazio (medição)", lambda r: r.failed_none_ts > 0),
    ("T1", "travamento (GPU cheia, parada ≥ 60 s)", lambda r: r.frozen_s >= 60),
    ("perda", "requisições perdidas", lambda r: (r.unserved + r.failed) > 0),
]
INK, MUTED, GRID = "#1f1f1e", "#73726c", "#d9d8d2"
HIT, MISS, NORUN = "#c2410c", "#f4f3ef", "#bdbcb6"


def panel(ax, d, xs, version, show_labels):
    for j, x in enumerate(xs):
        lv = d[(d.version == version) & (d.x == x)]
        ran = lv[lv.start_failed == 0]
        for i, (_, _, cond) in enumerate(ERRORS):
            if len(lv) == 0:
                color, txt = "white", ""
            elif i > 0 and len(ran) == 0:
                color, txt = NORUN, "não rodou"
            else:
                rows = lv if i == 0 else ran
                hits = sum(bool(cond(r)) for r in rows.itertuples())
                color, txt = (HIT if hits else MISS), f"{hits}/{len(rows)}"
            ax.add_patch(plt.Rectangle((j + 0.04, i + 0.04), 0.92, 0.92, color=color, lw=0))
            ax.text(j + 0.5, i + 0.5, txt, ha="center", va="center", fontsize=8,
                    color="white" if color == HIT else INK)
        served = ran.ok.sum() / ran.sent.sum() * 100 if len(ran) and ran.sent.sum() else None
        ax.text(j + 0.5, len(ERRORS) + 0.45, "—" if served is None else f"{served:.0f}%".replace(".", ","),
                ha="center", va="center", fontsize=8, color=MUTED)
    ax.set_xlim(0, len(xs)); ax.set_ylim(len(ERRORS) + 0.9, 0)
    ax.set_xticks([j + 0.5 for j in range(len(xs))]); ax.set_xticklabels(xs, fontsize=8)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(ERRORS))] + [len(ERRORS) + 0.45])
    ax.set_yticklabels([f"{e} · {lbl}" for e, lbl, _ in ERRORS] + ["atendidas"] if show_labels else [], fontsize=8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title({"base": "Prism base (c86d528)", "fixed": "com as correções"}[version], fontsize=9, color=INK, pad=22)


def main():
    src, figs = sys.argv[1], sys.argv[2]
    os.makedirs(figs, exist_ok=True)
    d = pd.read_csv(src).fillna(0)
    for axis, (title, suites, xlabel) in AXES.items():
        a = d[d.suite.isin(suites)].copy()
        if a.empty:
            continue
        a["x"] = [xlabel(r) for r in a.itertuples()]
        order = a.sort_values(["suite", "level"], key=lambda c: c.str.extract(r"([\d.]+)")[0].astype(float)
                              if c.name in ("suite", "level") else c)["x"].drop_duplicates().tolist()
        versions = [v for v in ("base", "fixed") if v in set(a.version)]
        fig, axs = plt.subplots(1, len(versions), figsize=(2.2 + 1.15 * len(order) * len(versions), 4.2),
                                squeeze=False)
        for k, v in enumerate(versions):
            panel(axs[0][k], a, order, v, k == 0)
        fig.suptitle(title, fontsize=10, color=INK, x=0.01, ha="left")
        fig.tight_layout()
        out = os.path.join(figs, f"limites__{axis}.png")
        fig.savefig(out, dpi=130)
        plt.close(fig)
        print(out)


if __name__ == "__main__":
    main()
