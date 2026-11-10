# F06.16 — Triagem das políticas novas: preempção por troca, residência preditiva, perda esperada e valor (2026-11-10)

Data: 2026-11-10 (desenho, implementação, smokes e campanha 01:25–08:21 UTC). Branch `scheduling-research`, commits
`f71435e` (literatura) … `b74c8e7` (análise). Código do servidor e da política dos 88 níveis: `0c88762` (nada em
`python/` mudou durante a campanha).

Glossário: **A0.2+A1** = despejo por ociosidade de 10 s com as restrições estruturais A1 (reserva de KV, quebra de
impasse em 30 s, residência mínima de 10 s); **A0.4** = troca por throughput/GB sem preempção + A1; **A9.2** = VLT ciente
da residência, sem preempção (referência desta triagem, D50); **A9.4** = A9.2 decidindo preemptar a cada troca; **A2.3**
= A9.2 com residência preditiva; **A3.1** = despejo por perda esperada de prazos; **A10.1** = troca por throughput só para
modelos com requisição viável; **S3 `k_A`=5** = prazo de TTFT de 5× o custo de ativação (~7 s num 8B); **S6 `k_R`** = prazo
de `k_R` trocas reais sem preempção (~16 s e ~63 s num 8B; `reports/registro/latencia_ref.md`, `c_rot.json`).

## Objetivo

Triagem barata (D53: 2 repetições) de quatro políticas novas, para decidir quais entram na confirmação de 5
repetições, sob o objetivo da D52: **justiça entre modelos sem grande perda de SLO**.

## Hipóteses

- H-A9.4: decidir a preempção a cada troca (preemptar só se as requisições salvas forem ≥ λ = 3 vezes as perdidas, regra
  do Shepherd, R10) captura o ganho da preempção quando ela é barata, sem o custo da preempção global (F6.0).
- H-A2.3: contar a chegada esperada de um modelo popular durante a ausência (R7) evita despejá-lo quando a fila esvazia
  por um instante e melhora a A9.2.
- H-A3.1: decidir pela contagem de prazos salvos × perdidos (R9) maximiza o SLO total, possivelmente à custa da justiça
  (favorece filas grandes).
- H-A10.1: filtrar a troca por throughput pelos modelos com requisição viável evita trocas inúteis da A0.4.

## Mudanças de código (arquivo, função, variável de ambiente, padrão)

| Arquivo | Mudança | Variável / padrão |
| --- | --- | --- |
| `policy/deadline.py` | `preempt_choice` (A9.4), termo preditivo em `eviction_cost` (A2.3), `loss_select` e `viable_count` (A3.1); `Decision.preempt` por vítima | `PRISM_LVF_PREEMPT` (`global`; `per_swap` = A9.4), `PRISM_LVF_PREEMPT_LAMBDA` (3), `PRISM_LVF_PREDICTIVE` (0), `PRISM_LOSS_THETA` (0) |
| `policy/simple_global.py` | `PRISM_EVICTION=loss` (A3.1) e `value` (A10.1, `_has_viable`); taxa de chegada por modelo em 60 s (`_arrival_rate`, `_typical_slo`); preempção por vítima nas ações; combinações inválidas dão erro | `PRISM_RATE_WINDOW_S` (60) |
| `polyaxon/extract_ovl.py`, `swap_cost.py`, `ovl_plots.py`, `f60_analysis.py` | evento `loss rotation` (`evict_loss`); análise aceita os jobs `f616-*` | — |
| `polyaxon/f6_16_suites.sh`, `f4_driver_start.sh f616`, `f616_table.py`, `f616_paired.py` | suítes, driver e tabelas da triagem | `F616_REPS` (2) |
| Testes | `tests/policy/test_f616.py` (16); 175 testes passam | — |

Literatura (`reports/registro/referencias.md`): R10 Shepherd (A9.4), R7 adendo (A2.3), R9 QLM (A3.1, A10.1).

## Configurações executadas

Por job (mesma janela, regra 3), 11 níveis: A0.2+A1, A0.4; A9.2 em S3 `k_A`=5, S6 `k_R`=1 e S6 `k_R`=4 (referência);
A9.4 e A2.3 em S3 `k_A`=5 e S6 `k_R`=1; A3.1 e A10.1 em S6 `k_R`=4. Cargas e justificativa de relevância como na F6.0
(C1 com 10 modelos, T1, C6 com 14 modelos, T3), 2 repetições. Sem preempção global (D52). Suítes
`polyaxon/configs/f616_<carga>_o<rep>_suite.tsv`.

**Por que A3.1 e A10.1 só no S6 `k_R`=4 (D53, opção 1):** as duas só trocam por requisições que ainda cumprem o prazo
depois de uma troca real sem preempção (~15,7 s num 8B). No S3 `k_A`=5 (~7 s) e no S6 `k_R`=1 (~16 s) nenhuma requisição
passa nesse teste: no smoke 1 (`f616-smoke`, `807890d9`) as duas fizeram 0 trocas e viraram despejo por ociosidade de
50 s. No S6 `k_R`=4 agem (smoke 2, `f616-smoke2`, `69968c1e`: 21 trocas por perda, 42 por valor).

## Execuções

| Job | uuid | Validador |
| --- | --- | --- |
| `f616-smoke` | `807890d9` | 4/4 VALIDA (A3.1 e A10.1 sem trocas: níveis mudados) |
| `f616-smoke2` | `69968c1e` | 3/3 VALIDA |
| `f616-c1n10-1` / `-2` | `dde876d0` / `70d66a57` | 11/11, 11/11 |
| `f616-t1-1` / `-2` | `d258a0ff` / `17633de5` | 11/11, 11/11 |
| `f616-c6n14-1` / `-2` | `839d7581` / `cf56c543` | 11/11, 11/11 |
| `f616-t3-1` / `-2` | `de837688` / `1f479900` | 11/11, 11/11 |

88/88 níveis VALIDA, nenhuma reexecução. Validador: `reports/data/F06/f616/validador/`; brutos em
`/mnt/scratch/scheduler/prism-raw/F6/f616/`.

## Resultados

Médias dos 8 jobs (`reports/data/F06/f616/analise/resumo_politicas.txt`); só TTFT dentro do prazo, sobre todas as
enviadas; justiça só com modelos com ≥ 10 requisições (`polyaxon/f60_fairness.py`).

| Nível | Política | total | pior quarto dos modelos | índice de Jain | TTFT p90 do pior modelo (s) | maior espera (s) |
| --- | --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 | A0.2+A1 | 70% | 8% | 0,718 | 419 | 463 |
| S3 `k_A`=5 | A0.4 | 57% | 26% | 0,855 | 97 | 142 |
| S3 `k_A`=5 | A9.2 (ref.) | 51% | 32% | 0,914 | 115 | 136 |
| S3 `k_A`=5 | A9.4 | 51% | 32% | 0,908 | 115 | 140 |
| S3 `k_A`=5 | A2.3 | 49% | 20% | 0,820 | 126 | 153 |
| S6 `k_R`=1 | A0.2+A1 | 74% | 9% | 0,735 | 419 | 463 |
| S6 `k_R`=1 | A0.4 | 68% | 36% | 0,908 | 97 | 142 |
| S6 `k_R`=1 | A9.2 (ref.) | 54% | 38% | 0,939 | 121 | 145 |
| S6 `k_R`=1 | A9.4 | 55% | 36% | 0,934 | 126 | 150 |
| S6 `k_R`=1 | A2.3 | 56% | 29% | 0,871 | 115 | 148 |
| S6 `k_R`=4 | A0.2+A1 | 85% | 20% | 0,804 | 419 | 463 |
| S6 `k_R`=4 | A0.4 | 96% | 79% | 0,990 | 97 | 142 |
| S6 `k_R`=4 | A9.2 (ref.) | 84% | 72% | 0,986 | 109 | 129 |
| S6 `k_R`=4 | A3.1 | 90% | 59% | 0,937 | 245 | 290 |
| S6 `k_R`=4 | A10.1 | 95% | 80% | 0,990 | 103 | 126 |

Diferenças pareadas no mesmo job, IC 95% por bootstrap sobre os 8 jobs (`pareado_ic.txt`; `*` = IC exclui 0):

| Política, nível | − A9.2 (ref.): total / pior quarto / Jain ×100 | − A0.4: total / pior quarto / Jain ×100 |
| --- | --- | --- |
| A9.4, S3 `k_A`=5 | −0,3 / −0,2 / −0,6 | −6,0 / **+5,5\*** / **+5,3\*** |
| A9.4, S6 `k_R`=1 | +0,9 / −1,8\* / −0,6 | **−12,9\*** / −0,6 / +2,5\* |
| A2.3, S3 `k_A`=5 | −2,3 / **−11,7\*** / **−9,4\*** | −8,0\* / −6,0 / −3,5 |
| A2.3, S6 `k_R`=1 | +2,0 / **−8,2\*** / **−6,9\*** | −11,7\* / −7,0\* / −3,7 |
| A3.1, S6 `k_R`=4 | +5,1\* / **−13,4\*** / −4,8\* (p90 do pior modelo +136 s\*) | −6,2\* / −20,6\* / −5,3\* |
| A10.1, S6 `k_R`=4 | **+10,6\*** / +8,3 / +0,4 | −0,8 / +1,1 / 0,0 |

- **H-A9.4 não confirmada (com λ = 3).** A A9.4 é, na prática, a A9.2: em 343 trocas com vítima ocupada, preemptou 13
  (4%); as outras 197 trocas tinham vítima ociosa, em que a preempção não custa nada. Mecanismo: com trocas de 6–16 s, as
  requisições "salvas" pela troca mais rápida são poucas (1–4 por troca) e a vítima ocupada tem 2–8 em execução, então
  salvas ≥ 3 × perdidas quase nunca acontece. Fica para a confirmação com λ = 1 (decisão do Gabriel).
- **H-A2.3 refutada.** Proteger modelos com chegada esperada piora a justiça (pior quarto −8 a −12 pontos, Jain −7 a −9
  contra a A9.2, IC exclui 0): os modelos com tráfego contínuo ficam, e os menos usados esperam mais, o mesmo defeito da
  A0.2+A1 em escala menor.
- **H-A3.1 confirmada:** ganha total (+5 contra a A9.2) e perde justiça e cauda (pior quarto −13, p90 do pior modelo
  +136 s): contar prazos favorece filas grandes.
- **H-A10.1 sem efeito:** no S6 `k_R`=4 quase toda espera é viável depois de uma troca, então o filtro raramente atua e a
  A10.1 é a A0.4 (nenhuma diferença significativa). Ganha da A9.2 no total (+10,6) porque a A0.4 também ganha.
- **A A0.4 é a linha de base forte sob o novo objetivo:** nos prazos S6 `k_R`=1 e `k_R`=4 é quase tão justa quanto as
  variantes do VLT e tem 10–17 pontos a mais de total. A A9.2 só ganha dela em justiça no prazo curto (S3 `k_A`=5: pior
  quarto +5,5\*, Jain +5,3\*, total −6,0 sem significância), o mesmo resultado da F6.0.

## Anomalias e investigações

1. **A3.1 e A10.1 sem trocas no smoke 1** (acima): desenho correto (nenhuma requisição salvável com prazo ≤ uma troca),
   níveis mudados para S6 `k_R`=4 (D53). Nenhuma correção de código.
2. Nenhum nível inválido, nenhum K1, nenhuma reexecução.

## Critérios de aceitação

| Critério | Situação |
| --- | --- |
| Testes unitários passando | OK: 175 |
| Linhas de base na mesma campanha | OK: A0.2+A1 e A0.4 em todo job |
| Diferenças pareadas com IC 95% | OK (2 repetições: triagem, D53) |
| Explicação mecânica das diferenças grandes | OK: A9.4 (λ e tamanho das filas), A2.3 (proteção dos populares), A3.1 (filas grandes), A10.1 (filtro inativo no prazo folgado) |

## Decisão (Gabriel, 2026-11-10, D54)

Entram na confirmação de 5 repetições: A9.2 e A2.1 sem preempção, **A9.4 com λ = 1**, contra A0.2+A1 e A0.4, nos
prazos S3 `k_A`=5, S6 `k_R`=1, **S6 `k_R`=2** e S6 `k_R`=4; A2.1 com preempção no S6 `k_R`=4 (D52). Saem A2.3, A3.1 e
A10.1.

## Pendências

- Confirmação F6.15 (5 repetições) com o escopo acima.
- A0.4 como linha de base forte: a confirmação mede A9.2 e A9.4 contra ela em todos os prazos.

## Reprodução

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
$PY -m unittest tests/policy/test_f616.py
bash polyaxon/f6_16_suites.sh
PRISM_JOB_SUFFIX=-f616-smoke2 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f616_smoke_suite.tsv PRISM_TIMEOUT=5400" polyaxon/submit.sh
bash polyaxon/f4_driver_start.sh f616   # estado reports/data/F06/f616/jobs.tsv
$PY polyaxon/f60_analysis.py reports/data/F06/f616/analise reports/data/F06/f616/validador/f616-*.csv
$PY polyaxon/f60_fairness.py reports/data/F06/f616/analise
$PY polyaxon/f616_table.py reports/data/F06/f616/analise > reports/data/F06/f616/analise/resumo_politicas.txt
$PY polyaxon/f616_paired.py reports/data/F06/f616/analise > reports/data/F06/f616/analise/pareado_ic.txt
```
