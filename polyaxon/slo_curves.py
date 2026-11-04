"""SLO curves (F2.12, PLANO_AGENTE.md section 5.4): attainment of each policy as the SLO level varies, in the three
views, from runs of policies that do not use the SLO (one run, every curve).

Usage: python3 polyaxon/slo_curves.py <data dir> <validator.csv> <dest dir> [--policies a,b,...]

<data dir> is a collect_reps.py directory (manifest.csv); only levels the validator (validate_run.py --csv) marks
VALIDA are used, averaged over repetitions. Grid (initial levels of section 5.4):
  S2  k_T ∈ {2, 5, 10, 25, 50, 100} × k_D ∈ {1.5, 2, 3, 5, 10, 20}    (P95 base; S2M, the P50 base, same grid)
  S3  k_A ∈ {0.5, 1, 2, 5, 10, 25, 50} × k_D (same)
(the initial levels of section 5.4, extended upwards; APPROVED lists the levels Gabriel approved, D19 and D23)
and S1 (1 s, 100 ms) for reference. Writes <dest>/curvas.csv (scenario, level, config, family, k_T/k_A, k_D, number of
repetitions, mean of each view and of the breakdown), <dest>/resumo.md (minimum attainable SLO at 90% and 99% per
policy and view; best policy at each k_T, and whether the order between policies changes along the curve) and one
figure per scenario and level, <dest>/<scenario>_<level>.png: one row for S2 and one for S2M, each with combined vs k_T
(k_D = KD_FIXED = 10), TTFT only vs k_T, TPOT only vs k_D; S3 TTFT only vs k_A in the first row. Needs pandas and
matplotlib (/mnt/scratch/scheduler/opt-env/bin/python).
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slo_metrics as sm  # noqa: E402

# section 5.4's initial levels, extended upwards (k_T 100, k_D 10/20, k_A 10/25/50) after the first look at the data:
# with every level of the initial grid the combined view was ≤ 3% (TPOT under multi-model sharing is ~4–5× TPOT_iso)
KT, KD, KA = (2, 5, 10, 25, 50, 100), (1.5, 2, 3, 5, 10, 20), (0.5, 1, 2, 5, 10, 25, 50)
# levels approved for the campaigns (D23 for S2/S2M on the D21 bases; k_A from D19), shaded in the figures
APPROVED = {"S2": {"k_T": (2, 5, 10, 25), "k_D": (1.5, 2, 3, 5)}, "S2M": {"k_T": (5, 10, 25, 50), "k_D": (3, 5, 10, 20)},
            "S3": {"k_A": (2, 5, 10, 25, 50)}}
KD_FIXED = 10
# validated categorical palette (dataviz skill, references/palette.md), slots in order; a policy keeps its color
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
DEFAULT_POLICIES = ["original", "idle10", "idle1", "tp_P0D1", "tp_P1D0", "pressure", "fair", "headroom"]
LABEL = {"original": "A0.1 original (50 s)", "idle10": "A0.2 limiar 10 s", "idle1": "limiar 1 s",
         "tp_P0D1": "A0.3 troca P0D1", "tp_P1D0": "troca P1D0", "pressure": "pressão", "fair": "rodízio",
         "headroom": "folga de KV"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
VIEWS = [("comb", "combinada"), ("so_ttft", "só TTFT"), ("so_tpot", "só TPOT")]


def specs():
    out = [("S1", None, None, "S1:ttft=1,tpot=0.1")]
    out += [(f, kt, kd, f"{f}:kT={kt},kD={kd}") for f in ("S2", "S2M") for kt in KT for kd in KD]
    out += [("S3", ka, kd, f"S3:kA={ka},kD={kd}") for ka in KA for kd in KD]
    return out


def valid_levels(data, vcsv):
    status = {(r["uuid"], r["source"]): r["status"] for r in csv.DictReader(open(vcsv))}
    ok = set()
    for m in csv.DictReader(open(os.path.join(data, "manifest.csv"))):
        if status.get((m["uuid"], m["source"])) == "VALIDA":
            ok.add((m["scenario"], m["config"], "r" + m["rep"], m["level"]))
    return ok


def compute(data, vcsv, policies):
    refs = sm.Refs()
    ok = valid_levels(data, vcsv)
    sp = specs()
    rows = []
    for d, (scenario, config, rep, level) in sm.levels(data):
        if config not in policies or (scenario, config, rep, level) not in ok:
            continue
        for (fam, k, kd, spec), m in zip(sp, sm.level_metrics(d, [s[3] for s in sp], refs)):
            rows.append({"cenário": scenario, "nível": level, "config": config, "rep": rep, "família": fam,
                         "k": k, "k_D": kd, **{c: m[c] for c in ("comb", "so_ttft", "so_tpot", "ambos_ok", "viola_so_ttft",
                                                                 "viola_so_tpot", "viola_ambos", "nao_atendidas",
                                                                 "viol_ttft_inevitavel", "viol_ttft_evitavel")}})
    df = pd.DataFrame(rows)
    keys = ["cenário", "nível", "config", "família", "k", "k_D"]
    g = df.groupby(keys, dropna=False)
    out = g.mean(numeric_only=True).join(g.size().rename("repetições")).reset_index()
    return out


def min_level(curve, target):
    """Smallest k whose attainment is ≥ target (curve: k -> fraction, increasing in k); None if never."""
    for k in sorted(curve):
        if curve[k] >= target:
            return k
    return None


def summary(c, dest):
    lines = ["# Curvas de SLO das políticas sem prazo (gerado por `polyaxon/slo_curves.py`)", "",
             "Médias sobre as repetições válidas. S2: SLO de TTFT = k_T·TTFT_base(m), de TPOT = k_D·TPOT_base(m), com a "
             "base P95 da carga do modelo em GPU dedicada (D20, D21); S2M: o mesmo com a base P50; "
             "S3: SLO de TTFT = k_A·Ĉ_at(m). Frações sobre todas as enviadas.", ""]
    for (fam, sc, lv), g in c[c["família"].isin(["S2", "S2M"])].groupby(["família", "cenário", "nível"]):
        lines += [f"## {fam}: {sc} {lv}", "",
                  f"SLO mínimo atingível em k_T ({fam}, k_D = {KD_FIXED} na vista combinada), 90% / 99%:", "",
                  "| política | repetições | combinada | só TTFT | só TPOT (em k_D) |", "| --- | --- | --- | --- | --- |"]
        for cfg, gc in g.groupby("config"):
            gk = gc[gc.k_D == KD_FIXED]
            comb = dict(zip(gk.k, gk.comb))
            tt = dict(zip(gk.k, gk.so_ttft))
            gd = gc[gc.k == max(KT)]
            tp = dict(zip(gd.k_D, gd.so_tpot))
            f = lambda cur: " / ".join(str(min_level(cur, t) or "—") for t in (0.9, 0.99))
            lines.append(f"| {LABEL.get(cfg, cfg)} | {int(gc['repetições'].min())} | {f(comb)} | {f(tt)} | {f(tp)} |")
        lines += ["", f"Melhor política na vista combinada (k_D = {KD_FIXED}) a cada k_T, e ordem entre as políticas:", ""]
        orders = []
        for kt in KT:
            gk = g[(g.k == kt) & (g.k_D == KD_FIXED)].sort_values("comb", ascending=False)
            orders.append(list(gk.config))
            lines.append(f"- k_T = {kt}: " + " > ".join(f"{LABEL.get(x, x)} ({v:.0%})" for x, v in zip(gk.config, gk.comb)))
        changes = sum(a != b for a, b in zip(orders, orders[1:]))
        lines += ["", f"A ordem muda {changes} vez(es) entre níveis consecutivos de k_T.", ""]
    open(os.path.join(dest, "resumo.md"), "w").write("\n".join(lines) + "\n")
    return lines


def figures(c, dest, policies):
    plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.edgecolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.labelcolor": INK, "font.size": 9, "legend.frameon": False,
                         "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
                         "lines.linewidth": 2})
    color = {p: COLORS[i] for i, p in enumerate(policies[:len(COLORS)])}  # fixed per policy across scenarios
    for (sc, lv), g in c[c["família"] != "S1"].groupby(["cenário", "nível"]):
        present = [p for p in policies if p in set(g.config) and p in color]
        fig, axs = plt.subplots(2, 4, figsize=(15, 7.0), sharey=True)
        panels = [(f, *pn) for f, name in (("S2", "S2 (base P95)"), ("S2M", "S2M (base P50)")) for pn in (
                  ("comb", "k", f"{name} combinada (k_D = {KD_FIXED})", "k_T", lambda x: x.k_D == KD_FIXED),
                  ("so_ttft", "k", f"{name} só TTFT", "k_T", lambda x: x.k_D == KD_FIXED),
                  ("so_tpot", "k_D", f"{name} só TPOT (k_T = {max(KT)})", "k_D", lambda x: x.k == max(KT)))]
        panels.insert(3, ("S3", "so_ttft", "k", "S3 só TTFT", "k_A", lambda x: x.k_D == KD_FIXED))
        axs[1, 3].axis("off")
        for ax, (fam, col, xcol, title, xl, sel) in zip(axs.flat, panels):
            for p in present:
                gp = g[(g["família"] == fam) & (g.config == p)]
                gp = gp[sel(gp)].sort_values(xcol)
                ax.plot(gp[xcol], gp[col], color=color[p], marker="o", markersize=4,
                        label=LABEL.get(p, p))
            ax.set_xscale("log")
            ax.set_xticks(sorted(set(g[g["família"] == fam][xcol].dropna())))
            ax.get_xaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
            ax.get_xaxis().set_minor_locator(matplotlib.ticker.NullLocator())
            lim = APPROVED[fam][xl]
            ax.axvspan(min(lim), max(lim), color="#f1f0ec", zorder=0, lw=0)  # the approved levels
            ax.set_title(title)
            ax.set_xlabel(xl)
            ax.set_ylim(0, 1.02)
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        for ax in axs[:, 0]:
            ax.set_ylabel("fração dentro do SLO")
        h, lab = axs[0, 0].get_legend_handles_labels()
        axs[1, 3].legend(h, lab, loc="center left", fontsize=9)
        fig.suptitle(f"{sc} {lv}: fração dentro do SLO por nível (médias das repetições válidas; faixa cinza = "
                     "níveis aprovados, D23)", x=0.01, ha="left",
                     fontsize=10.5, fontweight="bold", color=INK)
        fig.tight_layout()
        fig.savefig(os.path.join(dest, f"{sc}_{lv}.png"), bbox_inches="tight")
        plt.close(fig)


def main():
    args = sys.argv[1:]
    policies = DEFAULT_POLICIES
    if "--policies" in args:
        i = args.index("--policies")
        policies = args[i + 1].split(",")
        del args[i:i + 2]
    data, vcsv, dest = args
    os.makedirs(dest, exist_ok=True)
    c = compute(data, vcsv, policies)
    c.to_csv(os.path.join(dest, "curvas.csv"), index=False)
    print("\n".join(summary(c, dest)))
    figures(c, dest, policies)


if __name__ == "__main__":
    main()
