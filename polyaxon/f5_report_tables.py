#!/usr/bin/env python3
"""Markdown tables of the F05 report from f5_analysis.py's niveis.csv, pareado.csv and curvas_niveis.csv.

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f5_report_tables.py [<campaign dir>] > tabelas.md
Means over the 3 repetitions (jobs) of each workload; paired differences against A0.1_A1 with a 95% bootstrap CI over
the jobs (`*` = the CI excludes 0; with 3 jobs the CI is only indicative). Every SLO fraction is over all sent requests.
"""
import math
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from f4_analysis import boot_ci  # noqa: E402
from f5_analysis import CONFIGS, ORDER, REF  # noqa: E402

CAMP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "reports/data/F05/campanha")
NAME = {"A0.1": "A0.1", "A0.1_A1": "A0.1+A1", "A0.2_A1": "A0.2+A1", "A0.4": "A0.4", "A0.4p": "A0.4p"}


def f(x, scale=1, d=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * scale:.{d}f}".replace(".", ",")


def table(head, rows):
    return ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head), *("| " + " | ".join(r) + " |" for r in rows)]


def per_config(n, cols):
    g = n.groupby(["carga", "config"])
    return g[cols].mean(), g.size()


def main():
    n = pd.read_csv(CAMP / "niveis.csv")
    p = pd.read_csv(CAMP / "pareado.csv")
    c = pd.read_csv(CAMP / "curvas_niveis.csv")
    loads = [w for w in ORDER if w in set(n.carga)]
    num = n.select_dtypes("number").columns
    m = n.groupby(["carga", "config"])[list(num)].mean()
    imp = n.groupby(["carga", "config"]).impasse.sum()
    out = []

    out += ["## Tabela 1 — SLO absoluto (S1) e cauda, média das 3 repetições", "",
            "SLO S1: TTFT < 1, 2 e 5 s (só TTFT), TPOT < 100 ms (só TPOT), combinado a 1 s e 100 ms. Espera = TTFT, ou "
            "fim da janela − chegada para as não atendidas (D33). Impasses = níveis com T1 ≥ 100 s (D37), de 3.", ""]
    rows = []
    for w in loads:
        for cfg in CONFIGS:
            r = m.loc[(w, cfg)]
            rows.append([w, NAME[cfg], f(r.atendidas, 100), f(r.comb_1s, 100),
                         f"{f(r.ttft_1s, 100)} / {f(r.ttft_2s, 100)} / {f(r.ttft_5s, 100)}", f(r.tpot_100ms, 100),
                         f"{f(r.ttft_p50, 1, 2)} / {f(r.ttft_p90)}", f"{f(r.espera_p99, 1, 0)} / {f(r.espera_max, 1, 0)}",
                         f(r.frac_10x_mediana, 100), str(int(imp.loc[(w, cfg)])), f(r.ativacoes_min, 1, 1)])
    out += table(["carga", "config.", "atendidas (%)", "comb. 1 s (%)", "só TTFT 1/2/5 s (%)", "só TPOT 100 ms (%)",
                  "TTFT p50/p90 (s)", "espera p99/máx. (s)", "> 10× mediana (%)", "impasses", "ativações/min"], rows)

    out += ["", "## Tabela 2 — SLO relativo (S2 k_T=10, k_D=5; S6 e S6P k_R=1, k_D=5) e classificação das violações", "",
            "S2: base P95 da carga do modelo em GPU dedicada (D20, D21; `reports/registro/latencia_ref.md`). S6: prazo de "
            "TTFT = uma rotação real sem preempção (8B 15,7 s); S6P: com preempção (8B 6,4 s) (D42). Classificação "
            "das violações de TTFT do S2 (D43, % das enviadas): inevitável pela ativação / pela rotação / evitável só "
            "com residência prévia / evitável; ao lado, a inevitável antiga (só Ĉ_at). Pior modelo = fração combinada "
            "S2 do pior modelo.", ""]
    rows = []
    for w in loads:
        for cfg in CONFIGS:
            r = m.loc[(w, cfg)]
            rows.append([w, NAME[cfg], f"{f(r.s2_comb, 100)} / {f(r.s2_ttft, 100)} / {f(r.s2_tpot, 100)}",
                         f"{f(r.s6_ttft, 100)} / {f(r.s6p_ttft, 100)}",
                         " / ".join(f(r[f"s2_{g}"], 100) for g in ("inev_ativacao", "inev_rotacao", "evit_residencia",
                                                                   "evit")),
                         f(r.s2_inev_antiga, 100), f(r.s2_viol_tpot_em_troca, 100), f(r.s2_pior_modelo, 100)])
    out += table(["carga", "config.", "S2 comb./TTFT/TPOT (%)", "S6 / S6P só TTFT (%)",
                  "viol. TTFT S2: inev. ativ. / inev. rot. / evit. resid. / evit. (%)", "inev. antiga (%)",
                  "viol. TPOT em troca (%)", "pior modelo S2 (%)"], rows)

    out += ["", "## Tabela 3 — Ociosidade da GPU e modelos ativos (D44, D46; R1, R5–R7)", "",
            "Observada = 1 − utilização do `nvidia-smi`; esperada = 1 − min(1, Σ ρ_m dos residentes), ρ_m = taxa × segundos "
            "de GPU ocupada por requisição na GPU dedicada; política = observada − esperada. Residente com demanda = GB·s "
            "de modelos carregados e parados enquanto outro modelo tem fila, sobre os GB·s da GPU; memória desperdiçada "
            "= o mesmo a qualquer instante (R7). Modelos ativos = com requisição no sistema (R6): observado / esperado "
            "pela carga / residentes. Ociosidade por modelo = fração do tempo sem requisição (R1).", ""]
    rows = []
    for w in loads:
        for cfg in CONFIGS:
            r = m.loc[(w, cfg)]
            rows.append([w, NAME[cfg], f"{f(r.idle_ocio_observada, 100)} / {f(r.idle_ocio_esperada, 100)} / "
                                       f"{f(r.idle_ocio_politica, 100)}",
                         f"{f(r.idle_ocio_residente_demanda, 100)} / {f(r.idle_ocio_residente_total, 100)}",
                         f"{f(r.idle_modelos_ativos_medio)} / {f(r.idle_modelos_ativos_esperado)} / "
                         f"{f(r.idle_modelos_residentes_medio)}", f(r.idle_ocio_por_modelo, 100),
                         f(r.idle_trocas_min, 1, 1)])
    out += table(["carga", "config.", "ociosidade obs. / esperada / política (%)", "residente com demanda / desperdiçada (%)",
                  "modelos ativos obs. / esp. / residentes", "ociosidade por modelo (%)", "ativações/min"], rows)

    out += ["", f"## Tabela 4 — Diferença pareada contra {NAME[REF]} (mesmo job), média e IC 95% (bootstrap, 3 jobs)", "",
            "Pontos percentuais nas frações; segundos nos tempos. `*` = IC exclui 0. Positivo melhora nas frações; "
            "negativo melhora nos tempos e na cauda.", ""]
    mets = [("s2_comb", "S2 comb. (pp)", 100), ("s6_ttft", "S6 só TTFT (pp)", 100), ("ttft_1s", "S1 só TTFT 1 s (pp)", 100),
            ("tpot_100ms", "só TPOT 100 ms (pp)", 100), ("ttft_p50", "TTFT p50 (s)", 1), ("ttft_p90", "TTFT p90 (s)", 1),
            ("espera_max", "espera máx. (s)", 1), ("frac_10x_mediana", "> 10× med. (pp)", 100),
            ("idle_ocio_politica", "ocio. política (pp)", 100)]
    rows = []
    for w in loads:
        for cfg in CONFIGS:
            if cfg == REF:
                continue
            ps = p[(p.carga == w) & (p.config == cfg)]
            cells = []
            for k, _, sc in mets:
                ds = [x for x in ps[f"dif_{k}"] if not math.isnan(x)]
                mean = sum(ds) / len(ds) if ds else math.nan
                lo, hi = boot_ci(ds)
                star = "*" if not math.isnan(lo) and (lo > 0 or hi < 0) else ""
                cells.append(f"{f(mean, sc)}{star}")
            rows.append([w, NAME[cfg], *cells])
    out += table(["carga", "config. − A0.1+A1", *(lbl for _, lbl, _ in mets)], rows)

    out += ["", "## Tabela 5 — SLO mínimo atingível (90% / 99% das requisições), média das repetições", "",
            "Menor nível da família em que a média das 3 repetições atende a fração pedida; — = nunca na grade. S2 e S2M: "
            "k_T na vista só TTFT (grade 2–100), k_D na só TPOT (com k_T = 100, grade 1,5–20); S6 e S6P: k_R na só TTFT "
            "(grade 0,5–8; k_D = 5).", ""]
    cm = c.groupby(["carga", "config", "família", "k", "k_D"])[["comb", "so_ttft", "so_tpot"]].mean().reset_index()

    def minlev(sel, col, xcol, t):
        s = sel.sort_values(xcol)
        hit = s[s[col] >= t]
        return f"{hit[xcol].iloc[0]:g}".replace(".", ",") if len(hit) else "—"

    rows = []
    for w in loads:
        for cfg in CONFIGS:
            g = cm[(cm.carga == w) & (cm.config == cfg)]
            cell = []
            for fam, col, xcol, cond in (("S2", "so_ttft", "k", lambda x: x.k_D == 5),
                                         ("S2", "so_tpot", "k_D", lambda x: x.k == 100),
                                         ("S2M", "so_ttft", "k", lambda x: x.k_D == 5),
                                         ("S6", "so_ttft", "k", lambda x: x.k_D == 5),
                                         ("S6P", "so_ttft", "k", lambda x: x.k_D == 5)):
                sel = g[g["família"] == fam]
                sel = sel[cond(sel)]
                cell.append(f"{minlev(sel, col, xcol, 0.9)} / {minlev(sel, col, xcol, 0.99)}")
            rows.append([w, NAME[cfg], *cell])
    out += table(["carga", "config.", "S2 k_T só TTFT", "S2 k_D só TPOT", "S2M k_T só TTFT", "S6 k_R só TTFT",
                  "S6P k_R só TTFT"], rows)

    out += ["", "## Tabela 6 — Varredura de ρ_mem (10 / 14 / 19 modelos de 8B: ρ_mem 1,07 / 1,49 / 2,03)", "",
            "C1: taxa fixa de 0,2 req/s por modelo (a taxa total cresce com o número de modelos); C6: taxa total fixa de "
            "2 req/s repartida por Zipf. Cada célula: 10 / 14 / 19 modelos.", ""]
    rows = []
    for base in ("C1", "C6"):
        for cfg in CONFIGS:
            ws = [f"{base}n{k}" for k in (10, 14, 19)]
            g = lambda col, sc=1, d=1: " / ".join(f(m.loc[(w, cfg)][col], sc, d) for w in ws)
            rows.append([base, NAME[cfg], g("s2_comb", 100), g("s6_ttft", 100), g("ttft_p50", 1, 2), g("ttft_p90"),
                         g("espera_max", 1, 0), g("idle_ocio_politica", 100), g("ativacoes_min", 1, 1),
                         " / ".join(str(int(imp.loc[(w, cfg)])) for w in ws)])
    out += table(["base", "config.", "S2 comb. (%)", "S6 só TTFT (%)", "TTFT p50 (s)", "TTFT p90 (s)", "espera máx. (s)",
                  "ocio. política (%)", "ativações/min", "impasses"], rows)
    print("\n".join(out))


if __name__ == "__main__":
    main()
