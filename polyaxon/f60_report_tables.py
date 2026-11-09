#!/usr/bin/env python3
"""F6.0 report tables (Markdown) and the trade-off figure, from polyaxon/f60_analysis.py and f60_fairness.py outputs.

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f60_report_tables.py <analysis dir> <figure.png>
Writes <analysis dir>/tabelas.md. Every SLO is the fraction of ALL sent requests (unserved = miss, strict <), as in
the F5 tables. Table 1 is the report standard (CLAUDE.md rule 7): TTFT-only at 1/2/5 s (computed here from the
extracted requests.csv), TPOT-only 100 ms and combined 1 s/100 ms (S1), TTFT p50/p90, wait p99/max (D33).
"""
import math
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

LV = {"S3k5": "S3 k_A=5 (~7 s)", "S6k1": "S6 k_R=1 (~16 s)", "S6k4": "S6 k_R=4 (~63 s)"}
POL = {"edf": "A2.1 EDF", "lvf": "A9.1 VLT", "lvfr": "A9.2 VLT residência"}
BASE = {"A0.2_A1": "A0.2+A1 (ociosidade 10 s)", "A0.4": "A0.4 (troca por throughput)"}
W = {"C1n10": "C1, 10 modelos (fome de memória)", "T1": "T1 (trace do Prism)", "C6n14": "C6, 14 modelos (popularidade que muda)",
     "T3": "T3 (trace Azure Functions)"}


def nome(cfg):
    if cfg in BASE:
        return BASE[cfg]
    p, lv, pre = cfg.rsplit("_", 2)
    return f"{POL[p]}, {'com' if pre == 'p1' else 'sem'} preempção"


def pct(x):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.0f}%"


def ci(m, lo, hi, scale=100, d=1, unit=""):
    s = lambda v: f"{v * scale:+.{d}f}"
    star = " *" if lo * hi > 0 else ""
    return f"{s(m)}{unit} [{s(lo)}, {s(hi)}]{star}"


def ttft_cols(root, n):
    """TTFT-only at 1/2/5 s from the extracted requests (strict <, unserved = miss)."""
    out = []
    for _, r in n.iterrows():
        q = pd.read_csv(root / "levels" / r["job"] / r["config"] / r["cenário"] / r["nível"] / "requests.csv")
        ok = q["status"] == "ok"
        out.append({k: ((ok) & (q["ttft"] < s)).sum() / len(q) for k, s in (("t1", 1), ("t2", 2), ("t5", 5))})
    return pd.DataFrame(out, index=n.index)


def main():
    root = pathlib.Path(sys.argv[1])
    fig_path = pathlib.Path(sys.argv[2])
    n = pd.read_csv(root / "niveis.csv")
    n = n.join(ttft_cols(root, n))
    j = pd.read_csv(root / "justica.csv")
    r = pd.read_csv(root / "resumo.csv")
    jr = pd.read_csv(root / "justica_resumo.csv")
    md = ["# F6.0: tabelas (gerado por polyaxon/f60_report_tables.py)\n",
          "Médias dos 8 jobs (4 cargas × 2 repetições); frações sobre todas as enviadas; IC 95% por bootstrap sobre os "
          "jobs (diferenças pareadas no mesmo job); `*` = IC exclui 0.\n"]

    order = list(BASE) + [f"{p}_{lv}_p{q}" for lv in LV for p in POL for q in (0, 1)]
    md.append("\n## Tabela 1: padrão dos relatórios (S1: TTFT só 1/2/5 s, TPOT só 100 ms, combinado 1 s/100 ms)\n")
    md.append("| Configuração | Nível de prazo enviado | servidas | TTFT 1 s | TTFT 2 s | TTFT 5 s | TPOT 100 ms | combinado | "
              "TTFT p50 / p90 (s) | espera p99 / máx. (s) | > 10× mediana |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in order:
        x = n[n.config == c]
        lv = c.rsplit("_", 2)[1] if c not in BASE else None
        md.append(f"| {nome(c)} | {LV[lv] if lv else '—'} | {pct(x.atendidas.mean())} | {pct(x.t1.mean())} | "
                  f"{pct(x.t2.mean())} | {pct(x.t5.mean())} | {pct(x.S1_so_tpot.mean())} | {pct(x.S1_comb.mean())} | "
                  f"{x.ttft_p50.mean():.0f} / {x.ttft_p90.mean():.0f} | {x.espera_p99.mean():.0f} / "
                  f"{x.espera_max.mean():.0f} | {pct(x.frac_10x_mediana.mean())} |")

    md.append("\n## Tabela 2: SLO no nível de prazo de cada braço (S3 / S6), três vistas\n")
    md.append("As linhas de base são avaliadas no mesmo nível depois da execução (não recebem prazo).\n")
    md.append("| Nível | Configuração | só TTFT | só TPOT | combinado |")
    md.append("| --- | --- | --- | --- | --- |")
    for lv in LV:
        for c in list(BASE) + [f"{p}_{lv}_p{q}" for p in POL for q in (0, 1)]:
            x = n[n.config == c]
            md.append(f"| {LV[lv]} | {nome(c)} | {pct(x[f'{lv}_so_ttft'].mean())} | {pct(x[f'{lv}_so_tpot'].mean())} | "
                      f"{pct(x[f'{lv}_comb'].mean())} |")

    md.append("\n## Tabela 3: só TTFT no nível próprio, por carga (média das 2 repetições)\n")
    md.append("| Nível | Carga | " + " | ".join(nome(c) for c in BASE) + " | " +
              " | ".join(f"{POL[p]} sem / com" for p in POL) + " |")
    md.append("| --- | --- |" + " --- |" * (len(BASE) + len(POL)))
    for lv in LV:
        for w in W:
            x = n[n.carga == w]
            g = lambda c: x[x.config == c][f"{lv}_so_ttft"].mean()
            md.append(f"| {LV[lv]} | {W[w]} | " + " | ".join(pct(g(c)) for c in BASE) + " | " +
                      " | ".join(f"{pct(g(f'{p}_{lv}_p0'))} / {pct(g(f'{p}_{lv}_p1'))}" for p in POL) + " |")

    a = r[(r.tabela == "vs_base") & (r.carga == "todas")]
    for b in BASE:
        md.append(f"\n## Tabela 4{'a' if b == 'A0.2_A1' else 'b'}: braço − {BASE[b]}, pareado no job, nível próprio\n")
        md.append("| Política | Nível | Preempção | só TTFT (pontos) | combinado (pontos) | TTFT p90 (s) | espera máx. (s) |")
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for p in POL:
            for lv in LV:
                for q in (0, 1):
                    x = a[(a.politica == p) & (a.nivel == lv) & (a.preempcao == q) & (a.base == b)].iloc[0]
                    md.append(f"| {POL[p]} | {LV[lv]} | {'com' if q else 'sem'} | "
                              f"{ci(x.dif_so_ttft, x.dif_so_ttft_ic_inf, x.dif_so_ttft_ic_sup)} | "
                              f"{ci(x.dif_comb, x.dif_comb_ic_inf, x.dif_comb_ic_sup)} | "
                              f"{ci(x.dif_ttft_p90, x.dif_ttft_p90_ic_inf, x.dif_ttft_p90_ic_sup, 1, 0)} | "
                              f"{ci(x.dif_espera_max, x.dif_espera_max_ic_inf, x.dif_espera_max_ic_sup, 1, 0)} |")

    pr = r[(r.tabela == "preempt") & (r.carga == "todas")]
    s3 = r[(r.tabela == "s3_hipotese") & (r.carga == "todas")]
    md.append("\n## Tabela 5: efeito da preempção (com − sem, mesmo job) e a hipótese do S3 (D49)\n")
    md.append("| Política | Δ S3 k_A=5 | Δ S6 k_R=1 | Δ S6 k_R=4 | interação Δ(S3) − Δ(S6 k_R=4), só TTFT | idem, combinado |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    for p in POL:
        d = {lv: pr[(pr.politica == p) & (pr.nivel == lv)].iloc[0] for lv in LV}
        x = s3[s3.politica == p].iloc[0]
        md.append(f"| {POL[p]} | " + " | ".join(ci(d[lv].dif_so_ttft, d[lv].dif_so_ttft_ic_inf, d[lv].dif_so_ttft_ic_sup)
                                               for lv in LV) +
                  f" | {ci(x.interacao_so_ttft, x.interacao_so_ttft_ic_inf, x.interacao_so_ttft_ic_sup)} | "
                  f"{ci(x.interacao_comb, x.interacao_comb_ic_inf, x.interacao_comb_ic_sup)} |")

    md.append("\n## Tabela 6: justiça entre modelos (só TTFT, nível próprio; modelos com ≥ 10 requisições)\n")
    md.append("| Nível | Configuração | pior modelo | pior quarto dos modelos | modelo mediano | índice de Jain | "
              "TTFT p90 do pior modelo (s) | maior espera (s) |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for lv in LV:
        for c in list(BASE) + [f"{p}_{lv}_p{q}" for p in POL for q in (0, 1)]:
            x = j[j.config == c]
            md.append(f"| {LV[lv]} | {nome(c)} | {pct(x[f'{lv}_pior_ttft'].mean())} | {pct(x[f'{lv}_quartil_ttft'].mean())} | "
                      f"{pct(x[f'{lv}_mediana_ttft'].mean())} | {x[f'{lv}_jain_ttft'].mean():.3f} | "
                      f"{x[f'{lv}_pior_p90_s'].mean():.0f} | {x[f'{lv}_pior_espera_s'].mean():.0f} |")

    ja = jr[jr.carga == "todas"]
    for b in BASE:
        md.append(f"\n## Tabela 7{'a' if b == 'A0.2_A1' else 'b'}: justiça, braço − {BASE[b]}, pareado no job\n")
        md.append("| Política | Nível | Preempção | pior quarto (pontos) | Jain (×100) | p90 do pior modelo (s) | maior espera (s) |")
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for p in POL:
            for lv in LV:
                for q in (0, 1):
                    x = ja[(ja.politica == p) & (ja.nivel == lv) & (ja.preempcao == q) & (ja.base == b)].iloc[0]
                    md.append(f"| {POL[p]} | {LV[lv]} | {'com' if q else 'sem'} | "
                              f"{ci(x.dif_quartil_ttft, x.dif_quartil_ttft_ic_inf, x.dif_quartil_ttft_ic_sup)} | "
                              f"{ci(x.dif_jain_ttft, x.dif_jain_ttft_ic_inf, x.dif_jain_ttft_ic_sup)} | "
                              f"{ci(x.dif_pior_p90_s, x.dif_pior_p90_s_ic_inf, x.dif_pior_p90_s_ic_sup, 1, 0)} | "
                              f"{ci(x.dif_pior_espera_s, x.dif_pior_espera_s_ic_inf, x.dif_pior_espera_s_ic_sup, 1, 0)} |")
    (root / "tabelas.md").write_text("\n".join(md) + "\n")

    # figure: total vs worst quarter, one panel per deadline level; colour = policy (fixed order), hollow = preemption
    colors = {"A0.2_A1": "#2a78d6", "A0.4": "#eb6834", "edf": "#1baf7a", "lvf": "#eda100", "lvfr": "#e87ba4"}
    short = {"A0.2_A1": "ociosidade 10 s", "A0.4": "throughput", "edf": "EDF", "lvf": "VLT", "lvfr": "VLT residência"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), sharey=True)
    for ax, lv in zip(axes, LV):
        for c in list(BASE) + [f"{p}_{lv}_p{q}" for p in POL for q in (0, 1)]:
            key = c if c in BASE else c.split("_")[0]
            hollow = c.endswith("_p1")
            xv = 100 * n[n.config == c][f"{lv}_so_ttft"].mean()
            yv = 100 * j[j.config == c][f"{lv}_quartil_ttft"].mean()
            ax.scatter(xv, yv, s=70, facecolors="none" if hollow else colors[key], edgecolors=colors[key],
                       linewidths=2, zorder=3)
            if key == "A0.2_A1":  # the point of the figure: direct label; the rest via the legend
                ax.annotate(short[key], (xv, yv), textcoords="offset points", xytext=(-8, 8), ha="right",
                            fontsize=8, color="#52514e")
        ax.margins(x=0.12, y=0.08)
        ax.set_title(LV[lv], fontsize=10, color="#0b0b0b")
        ax.set_xlabel("total dentro do prazo (só TTFT, %)", fontsize=9, color="#52514e")
        ax.grid(color="#e6e5e0", linewidth=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#52514e", labelsize=8)
    axes[0].set_ylabel("pior quarto dos modelos dentro do prazo (%)", fontsize=9, color="#52514e")
    fig.suptitle("F6.0: total × pior quarto dos modelos (média de 8 jobs); cheio = sem preempção, vazado = com",
                 fontsize=10, color="#0b0b0b")
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker="o", linestyle="", markersize=8, color=colors[k], label=short[k]) for k in colors]
    handles += [Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor="#52514e",
                       markeredgecolor="#52514e", label="sem preempção"),
                Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor="none",
                       markeredgecolor="#52514e", markeredgewidth=2, label="com preempção")]
    fig.legend(handles=handles, loc="lower center", ncol=7, frameon=False, fontsize=8.5, labelcolor="#52514e")
    fig.subplots_adjust(bottom=0.22)
    fig.patch.set_facecolor("#fcfcfb")
    for ax in axes:
        ax.set_facecolor("#fcfcfb")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=150)
    print(f"{root / 'tabelas.md'}, {fig_path}")


if __name__ == "__main__":
    main()
