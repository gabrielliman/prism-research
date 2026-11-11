"""F6.15 report tables (Markdown, Portuguese) from f615_compare.py and f615_decomp.py outputs.

Usage: f615_report_tables.py <analysis dir>   writes <dir>/tabelas.md
Tables: (A) fairness and tails per level (means over the jobs); (B) pooled paired differences of each arm against
A0.4, A0.2+A1 and A9.2 at the arm's level, 95% CI (stratified bootstrap over the 20 jobs), three SLO views plus
fairness; (C) the same per workload (5 reps) for total and worst quarter; (D) violation decomposition. The rule-7
table (TTFT 1/2/5 s, TPOT kD 2/5, combined, 100 ms) is tabela_padrao.md, written by f615_compare.py.
"""
import sys

import pandas as pd

D = sys.argv[1].rstrip("/") + "/"
t = pd.read_csv(D + "tabela_politicas.csv")
p = pd.read_csv(D + "pareado.csv")
dec = pd.read_csv(D + "decomposicao.csv")
LV = {"S3k5": "S3 `k_A`=5 (~7 s)", "S6k1": "S6 `k_R`=1 (~16 s)", "S6k2": "S6 `k_R`=2 (~31 s)",
      "S6k4": "S6 `k_R`=4 (~63 s)"}
PT = {"A0.2+A1 idle eviction 10 s": "A0.2+A1 (ociosidade 10 s)", "A0.4 throughput swap": "A0.4 (troca por throughput)",
      "A9.2 VLT residency": "A9.2 (VLT residência)", "A2.1 EDF": "A2.1 (EDF)",
      "A9.4 VLT per-swap preempt (lambda 1)": "A9.4 (VLT, preempção por troca, λ=1)",
      "A2.1 EDF + preemption": "A2.1 (EDF) com preempção"}
W = {"C1n10": "C1", "T1": "T1", "C6n14": "C6", "T3": "T3"}
f = lambda v, d=0: f"{v:.{d}f}".replace(".", ",")
md = ["# F6.15: tabelas (gerado por `polyaxon/f615_report_tables.py`)\n",
      "Frações sobre todas as enviadas; só TTFT no prazo do nível; justiça com modelos de ≥ 10 requisições; IC 95% por "
      "bootstrap estratificado por carga sobre os 20 jobs (diferenças pareadas no mesmo job); `*` = IC exclui 0.\n"]

pad = open(D + "tabela_padrao.md").read()
for en, pt in PT.items():
    pad = pad.replace(f"| {en} (", f"| {pt} (").replace(f"| {en} |", f"| {pt} |")
for lv, nome in LV.items():
    pad = pad.replace(f"({lv})", f"— {nome}")
md += ["\n## Tabela P: padrão dos relatórios (CLAUDE.md regra 7, D56; média dos 20 jobs)\n",
       "TTFT só 1/2/5 s (estrito); TPOT só como no artigo do Prism, `k_D` × P95 dedicado com `k_D` = 2 e 5 (S1D); "
       "combinado TTFT < 1 s e TPOT ≤ 5×P95; TPOT 100 ms como referência secundária. Gerada por "
       "`polyaxon/f615_compare.py` (`tabela_padrao.md`).\n", pad]

md += ["\n## Tabela A: total, justiça e caudas por nível (média dos 20 jobs)\n",
       "| Nível | Política | total | pior quarto | pior modelo | Jain ×100 | TTFT p90 do pior modelo (s) | "
       "TTFT p50 / p90 (s) | espera p99 / máx. (s) | rotações | preemptadas |",
       "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
for lv in LV:
    for g in t[(t.nivel == lv) & (t.carga == "todas")].to_dict("records"):
        md.append(f"| {LV[lv]} | {PT[g['politica']]} | {f(g['total %'])}% | {f(g['worst quarter %'])}% | "
                  f"{f(g['worst model %'])}% | {f(g['Jain x100'])} | {f(g['worst-model p90 s'])} | "
                  f"{f(g['TTFT p50 s'])} / {f(g['TTFT p90 s'])} | {f(g['wait p99 s'])} / {f(g['max wait s'])} | "
                  f"{f(g['rotations'])} | {f(g['preempted'])} |")

KEY = [("total %", "só TTFT (pts)"), ("TPOT 5xP95 %", "só TPOT 5×P95 (pts)"), ("total comb %", "combinado (pts)"),
       ("worst quarter %", "pior quarto (pts)"), ("Jain x100", "Jain ×100"), ("worst-model p90 s", "p90 pior modelo (s)"),
       ("max wait s", "maior espera (s)")]


def ci(r, d=1):
    return f"{f(r.media, d)} [{f(r.ic_lo, d)}; {f(r.ic_hi, d)}]{'\\*' if r.sig else ''}"


for ref, tag in (("A0.4 throughput swap", "B1"), ("A9.2 VLT residency", "B2"), ("A0.2+A1 idle eviction 10 s", "B3")):
    md += [f"\n## Tabela {tag}: braço − {PT[ref]}, pareado no job, no nível do braço (20 jobs)\n",
           "| Nível | Braço | " + " | ".join(k[1] for k in KEY) + " |", "| --- | --- |" + " --- |" * len(KEY)]
    q = p[(p.ref == ref) & (p.carga == "todas")]
    for lv in LV:
        for braco, g in q[q.nivel == lv].groupby("braco", sort=False):
            g = g.set_index("metrica")
            md.append(f"| {LV[lv]} | {PT[braco]} | " + " | ".join(ci(g.loc[k[0]]) for k in KEY) + " |")

md += ["\n## Tabela C: por carga (5 repetições), braço − A0.4: total só TTFT / pior quarto (pontos)\n",
       "| Nível | Braço | " + " | ".join(W.values()) + " |", "| --- | --- |" + " --- |" * len(W)]
q = p[(p.ref == "A0.4 throughput swap") & (p.carga != "todas")]
for lv in LV:
    for braco, g in q[q.nivel == lv].groupby("braco", sort=False):
        cell = []
        for w in W:
            a = g[(g.carga == w) & (g.metrica == "total %")].iloc[0]
            b = g[(g.carga == w) & (g.metrica == "worst quarter %")].iloc[0]
            cell.append(f"{f(a.media, 1)}{'\\*' if a.sig else ''} / {f(b.media, 1)}{'\\*' if b.sig else ''}")
        md.append(f"| {LV[lv]} | {PT[braco]} | " + " | ".join(cell) + " |")

NM = {"A0.2_A1": "A0.2+A1 (ociosidade 10 s)", "A0.4": "A0.4 (troca por throughput)", "lvfr": "A9.2 (VLT residência)",
      "edf": "A2.1 (EDF)", "lvfp": "A9.4 (VLT, preempção por troca, λ=1)"}
md += ["\n## Tabela D: decomposição das violações de TTFT (% das enviadas, média dos 20 jobs)\n",
       "Inevitável = o prazo é menor que o custo de ativação (`Ĉ_at`) ou da troca mais rápida (`Ĉ_rot` com preempção); "
       "evitável só com decisão antes da chegada = o prazo cobre o custo mas não o custo + um ciclo do controlador; "
       "TPOT em troca = violações de TPOT com o decode sobreposto a uma ativação/desativação "
       "(`polyaxon/slo_metrics.py`).\n",
       "| Nível | Política | no prazo | inevitável (ativação) | inevitável (troca) | evitável só antes da chegada | "
       "evitável | TPOT violado em troca |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
s = dec.groupby(["nivel", "config"], sort=False).mean(numeric_only=True)
for lv in LV:
    for cfg in ["A0.2_A1", "A0.4", f"lvfr_{lv}_p0", f"edf_{lv}_p0", f"lvfp_{lv}_ps"] + (["edf_S6k4_p1"] if lv == "S6k4" else []):
        r = s.loc[(lv, cfg)]
        nm = NM.get(cfg, NM.get(cfg.split("_")[0])) + (" com preempção" if cfg.endswith("_p1") else "")
        md.append(f"| {LV[lv]} | {nm} | {f(100 * r.so_ttft)}% | {f(100 * r.viol_ttft_inev_ativacao, 1)}% | "
                  f"{f(100 * r.viol_ttft_inev_rotacao, 1)}% | {f(100 * r.viol_ttft_evit_residencia, 1)}% | "
                  f"{f(100 * r.viol_ttft_evit, 1)}% | {f(100 * r.viol_tpot_em_troca, 1)}% |")
open(D + "tabelas.md", "w").write("\n".join(md) + "\n")
print(D + "tabelas.md")
