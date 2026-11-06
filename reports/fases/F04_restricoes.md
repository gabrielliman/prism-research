# F04 — Restrições estruturais (A1): reserva de KV, detector de impasse e residência mínima

Data de início: 2026-11-05 / fim: 2026-11-06
Commits: nenhum ainda. Código sobre `d6afc63` (F3) + código da D30 (D35) + mudanças da F4, no worktree `f3-cargas`; versão
congelada em `reports/data/F04/codigo/f4_smoke.diff` (sha256 `d7f2c4d2…`) e `f4_camp.diff` (sha256 `11bb052c…`, mesmo
código de política, mais suítes e o driver).

## Objetivo

Eliminar o impasse T1 (`reports/erros.md`) independentemente da política de escolha, com as três restrições da seção A1
do plano, e verificar que elas não pioram os cenários sem impasse.

## Hipóteses

- **H1.** O T1 vem da conta de memória do controlador, que ignora os 5% da GPU que o kvcached nunca usa para KV
  (7,2 GB). Somando esse piso à exigência de ativação (A1.1), a política deixa de encher a GPU de pesos até abaixo do
  piso, que é o caminho do T1 visto na F1.1 (14 modelos) e na F3 (tamanhos realistas).
- **H2.** A A1.1 sozinha não basta: depois da ativação, o KV dos modelos residentes cresce de novo até o piso, e a
  memória fica fragmentada entre eles, sem página para a requisição da frente de nenhum modelo. O detector (A1.2)
  cobre esse caso.
- **H3.** Nos cenários sem impasse (C2, T1), a A1 muda pouco: o piso tira no máximo um modelo residente, e o detector
  não dispara.
- **H4.** Com a A0.1, a A1 não resolve a fome de modelos que nunca entram (a A0.1 só despeja ociosos); isso é da
  política (F6), não da A1.

## Mudanças de código

| Arquivo | Mudança | Variável (padrão = comportamento anterior) |
| --- | --- | --- |
| `python/sglang/multi_model/scheduling/policy/structural.py` (novo) | funções puras: `activation_need_gb`, `kmin_gb`, `resident_long_enough`, `DeadlockDetector`, `deadlock_victim` | — |
| `policy/simple_global.py` | A1.1: `_activation_need_gb` usado por toda estratégia (ativação, troca por throughput, `edf`/`lvf`), com o piso do kvcached | `PRISM_KV_RESERVE_REQS` (0 = desligado), `PRISM_KV_FLOOR_FRAC` (0,05; só com a A1.1 ligada) |
| `policy/simple_global.py` | A1.2: `_deadlock_check` (passo 3c, depois das decisões da estratégia); vítima por `_keep_value` (o critério da A0.3, código compartilhado); despejo com preempção; nota `deadlock` no log de decisões | `PRISM_DEADLOCK_S` (0 = desligado) |
| `policy/simple_global.py` | A1.3 em todo caminho de despejo: ociosidade, pressão/`fair`, troca por throughput (`max` com `PRISM_SWAP_MIN_RESIDENCY`), `edf`/`lvf`, detector | `PRISM_MIN_RESIDENCY` (0 = desligado) |
| `polyaxon/extract_ovl.py`, `polyaxon/ovl_plots.py` | `Reason: deadlock break for <modelo>` → evento `evict_deadlock` | — |
| `tests/policy/test_structural.py` (novo, 27 testes); `tests/policy/test_deadline.py` (um teste isola o `K_min` com piso 0) | seção 0.6 | — |
| código da D30 (D35) | drenagem com prazo removida: `scheduler.py`, `io_struct.py`, `action.py`, `simple_global.py`, testes | — |

Testes: `$PY -m unittest tests/policy/test_structural.py tests/policy/test_deadline.py tests/controller/test_decision_log.py
tests/controller/test_estimators.py tests/robustness/test_deactivate_evict_stuck.py tests/robustness/test_model_service_alive.py
tests/workloads/test_workloads.py` (84 testes, OK) e `KVCACHED_SRC=/mnt/scratch/scheduler/kvcached $PY
test/multi-model/test_memory_robustness.py` (8, OK).

Estados cobertos pelos testes (seção 0.6): regra padrão inalterada; a ativação de 14 modelos que entra no piso do
kvcached (F1.1), bloqueada pela A1.1 em `idle`, `throughput` e `edf`; memória exatamente no limite; `K_min` maior que o
KV de ativação; a assinatura do T1 (residentes com fila, nada rodando, nenhum token) → despejo do de menor valor, com
preempção e log; antes de `Δ_imp`; com tokens fluindo; com ativação em andamento; residentes ociosos (caso do limiar,
não impasse); `T_min` protegendo o recém-ativado e ninguém elegível; troca por throughput no mesmo ciclo conta como
transição; desligado por padrão; despejo por ociosidade e por pressão esperando `T_min`.

## Parâmetros (D34, D37)

| Parâmetro | Valor | De onde |
| --- | --- | --- |
| `b` (A1.1) | 4 | mediana do lote em execução por residente com fila, A0.1 sem impasse (C1 3–6, T1 2–9) |
| piso | 0,05 × GPU = 7,2 GB | `kvcached/slab_allocator.py`, `GPU_UTILIZATION = 0.95` |
| `Δ_imp` (A1.2) | 30 s | maior trecho normal com GPU > 100 GB, 0% e pedido pendente: 13 s (74 níveis); impasses: 433–1120 s |
| `T_min` (A1.3) | 10 s | D25; acima do p99 do `Ĉ_at` do 8B (8,3 s) |
| critério de impasse (F4.5) | T1 ≥ 100 s | D37 (Gabriel); distribuição bimodal (≤ 34 s com A1 × ≥ 433 s sem) |

Calibração: `polyaxon/f4_calib.py` sobre os logs de decisão da F3 e da F6a (`reports/data/F04/calib/calib_niveis.tsv`).
O detector observa a soma dos `served_tokens` (contagem por segundo das engines), não as conclusões: em níveis sem
impasse há trechos de até 281 s sem conclusão, com a GPU trabalhando.

## Configurações executadas

**Braços** (um job = uma carga × quatro braços, mesma janela; ordem invertida a cada repetição, `polyaxon/f4_suites.sh`):

| Braço | Variáveis |
| --- | --- |
| A0.1 | `PRISM_IDLE_THRESHOLD=50` |
| A0.1_A1 | A0.1 + `PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10` |
| A0.3 | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=3` (sem drenagem, D30) |
| A0.3_A1 | A0.3 + as mesmas da A1 |

**Cargas e por que cada uma exercita a mudança** (seção 0.9; escopo do Gabriel em 2026-11-05: matriz do plano com 5
repetições + cargas da D29 com 2):

| Carga | Passo | Reps | Papel | Motivo |
| --- | --- | --- | --- | --- |
| C3 | `ovl_mix` 0,2 | 5 | impasse | T1 com a política original (F1.3: atende 2,6%) |
| C1n8 | `ovl_mem` 0,2, 8 modelos | 5 | impasse | T1 na F1.1 |
| C1n14 | `ovl_mem` 0,2, 14 modelos | 5 | impasse | T1 na F1.1 (4 de 4) |
| C2 | `ovl_phases` 0,5 | 5 | controle | sem impasse (F6a); mede piora |
| T1 | `ovl_trace_big` ts1 | 5 | controle | sem impasse (F6a: T1 = 0 em 33 níveis); mede piora |
| C6, C7, C8, T3 | tamanhos do Azure LLM | 2 | impasse | T1 em todo nível da F3 (580–1120 s; D29 item 4) |
| C10 | tamanhos 3B–32B | 2 | impasse | T1 em 25 s na F3 (o 32B nunca entra) |

Fora: C4 e C5 (zero ativações); T2 e T5 (sem impasse na F3, prompts curtos; T1 e C2 já são os controles); T4 (T1 de
670 s na F3, mas baixa prioridade na D29); C9 (mesmo mecanismo do C1/C6, sobre os quais é construída).

Execução: `polyaxon/f4_driver.py` (no máximo 3 jobs do Prism no nó contando todas as sessões; download um job por vez,
conferindo o pod no `run.log`; validador em cada job). Estado em `reports/data/F04/campanha_jobs.tsv`.

## Execuções

**Smoke (F4.3b, job `cbb45bf8`, suíte `polyaxon/configs/f4_smoke_suite.tsv`):**

| Nível | Validador | T1 (s) | Atendidas | SLO 1 s | Disparos A1.2 | Observação |
| --- | --- | --- | --- | --- | --- | --- |
| C6 A0.1 + A1 | VALIDA | 0 | 1193/1193 | 52,5% | 1 | a mesma carga (hash `19331633…`) congelou na F3 com A0.1: 245/1193, T1 580 s (outro dia; comparação só qualitativa) |
| C6 A0.3 + A1 | VALIDA | 0 | 1193/1193 | 62,5% | 0 | 62 trocas por throughput; o detector não precisou agir |
| C1n14 A0.1 + A1 | VALIDA | 34 | 475/831 | 12,0% | 2 | sem congelar (GPU 30–95% por minuto); 356 não atendidas por fome da A0.1 (modelos 12–14 nunca entram), ver anomalias |

**Campanha (F4.4, 2026-11-05 14:24 → 2026-11-06 03:16 UTC, 35 jobs, `polyaxon/f4_driver.py`):** 140 níveis.
- 134 VALIDA de primeira; 6 INVALIDA_SISTEMA, todos do C10 (P15, anomalia 2). Os dois jobs do C10 foram refeitos com a
  correção (`f4-c10-1b` `165cc1c7`, `f4-c10-2b` `86bd0ef2`, 2026-11-06): 8 de 8 VALIDA. A análise usa os jobs
  refeitos no lugar dos originais (código diferente).
- Um nível (`f4-c1n14-3` A0.3_A1) saiu INVALIDA por V13 e passou a VALIDA com a correção de medição do V13 (anomalia 3).
- Total usado: **140 de 140 níveis VALIDA**. Lista por job em `reports/data/F04/campanha_jobs.tsv` e
  `reports/data/F04/validador/f4-*.csv`; registro em `reports/registro/execucoes.csv` (fase F04).

**Verificação da folga (D37, 2026-11-06 10:08 → 13:08 UTC, 8 jobs, `polyaxon/f4_folga_suites.sh`, driver com
`bash polyaxon/f4_driver_start.sh folga`):** T3, C3, C7, C6 × {A0.3; A0.3 + A1 com folga 3 GB; A0.3 + A1 com folga 0}
× 2 repetições; 24 de 24 VALIDA (`reports/data/F04/validador/f4-folga-*.csv`, `reports/data/F04/folga_jobs.tsv`).

## Resultados

Tabelas geradas por `polyaxon/f4_report_tables.py` (a partir de `polyaxon/f4_analysis.py`: `niveis.csv`,
`pareado.csv`, `resumo.md` em `reports/data/F04/campanha/` e `reports/data/F04/folga/`). SLO S1 (TTFT 1/2/5 s, TPOT
100 ms; a base do S2/S2M das cargas da F3 só existe na F5), frações sobre todas as enviadas. A comparação é pareada
por job: os braços de uma repetição rodaram no mesmo job, em ordem alternada. Impasse = T1 ≥ 100 s (D37).
**Com 2 repetições, o IC por bootstrap só diz se as duas repetições tiveram o mesmo sinal; é indicativo, não um teste.**
Desvio do padrão de tabelas: não usei `report_tables.py`, que agrega por configuração e não pareia por job; as
colunas são as mesmas.

### Campanha F4.4

**Impasses (níveis com T1 ≥ 100 s / níveis VALIDA)**

| Carga | A0.1 | A0.1_A1 | A0.3 | A0.3_A1 | A0.3_A1h0 |
| --- | --- | --- | --- | --- | --- |
| C3 | 4/5 | 0/5 | 0/5 | 0/5 | – |
| C1n8 | 5/5 | 0/5 | 0/5 | 0/5 | – |
| C1n14 | 5/5 | 0/5 | 0/5 | 0/5 | – |
| C2 | 0/5 | 0/5 | 0/5 | 0/5 | – |
| T1 | 0/5 | 0/5 | 0/5 | 0/5 | – |
| C6 | 2/2 | 0/2 | 0/2 | 0/2 | – |
| C7 | 2/2 | 0/2 | 0/2 | 0/2 | – |
| C8 | 2/2 | 0/2 | 0/2 | 0/2 | – |
| T3 | 2/2 | 0/2 | 0/2 | 0/2 | – |
| C10 | 2/2 | 0/2 | 0/2 | 0/2 | – |

**Médias por braço** (S1; frações sobre todas as enviadas, em %; tempos em s)

| Carga | Braço | Atendidas | Comb. 1 s | TTFT 1 / 2 / 5 s | TPOT 100 ms | TTFT p50 / p90 | Espera p99 / máx. | Disparos A1.2 | Ativações/min |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C3 | A0.1 | 22,1 | 11,9 | 14,8 / 15,6 / 16,4 | 18,5 | 0,4 / 53,6 | 538 / 546 | 0,0 | 0,25 |
| C3 | A0.1_A1 | 100,0 | 58,1 | 68,4 / 72,3 / 75,0 | 86,1 | 0,3 / 230,5 | 338 / 347 | 0,0 | 0,48 |
| C3 | A0.3 | 100,0 | 18,6 | 22,1 / 25,2 / 29,7 | 83,6 | 23,0 / 79,9 | 126 / 146 | 0,0 | 6,25 |
| C3 | A0.3_A1 | 100,0 | 18,2 | 21,7 / 26,3 / 30,7 | 78,6 | 24,4 / 105,9 | 212 / 224 | 0,0 | 5,64 |
| C1n8 | A0.1 | 2,4 | 1,6 | 1,6 / 1,9 / 2,2 | 2,4 | 0,5 / 3,1 | 588 / 595 | 0,0 | 0,20 |
| C1n8 | A0.1_A1 | 100,0 | 57,8 | 75,4 / 79,9 / 82,5 | 78,6 | 0,3 / 169,3 | 342 / 351 | 0,0 | 0,31 |
| C1n8 | A0.3 | 100,0 | 37,0 | 42,0 / 46,5 / 51,7 | 84,5 | 5,3 / 52,2 | 95 / 122 | 0,0 | 4,56 |
| C1n8 | A0.3_A1 | 100,0 | 32,9 | 35,2 / 40,6 / 45,3 | 92,0 | 9,1 / 54,1 | 99 / 118 | 0,0 | 5,25 |
| C1n14 | A0.1 | 16,8 | 8,7 | 8,9 / 10,2 / 11,4 | 16,2 | 1,3 / 48,8 | 594 / 598 | 0,0 | 0,10 |
| C1n14 | A0.1_A1 | 66,0 | 5,7 | 7,2 / 8,4 / 10,4 | 41,3 | 163,7 / 421,5 | 572 / 591 | 2,2 | 0,80 |
| C1n14 | A0.3 | 100,0 | 7,4 | 8,5 / 10,3 / 12,7 | 74,2 | 78,3 / 227,3 | 314 / 351 | 0,0 | 5,84 |
| C1n14 | A0.3_A1 | 96,9 | 6,9 | 8,4 / 10,5 / 12,9 | 67,2 | 85,7 / 245,5 | 358 / 398 | 0,0 | 5,21 |
| C2 | A0.1 | 100,0 | 36,3 | 44,3 / 49,5 / 55,1 | 66,1 | 6,6 / 56,7 | 86 / 96 | 0,0 | 1,38 |
| C2 | A0.1_A1 | 100,0 | 41,9 | 52,9 / 58,7 / 64,6 | 61,5 | 0,9 / 44,5 | 74 / 85 | 0,0 | 1,40 |
| C2 | A0.3 | 100,0 | 54,5 | 61,4 / 66,4 / 71,9 | 80,2 | 0,7 / 34,5 | 65 / 83 | 0,0 | 1,78 |
| C2 | A0.3_A1 | 100,0 | 54,5 | 66,0 / 71,5 / 76,7 | 77,8 | 0,4 / 25,3 | 52 / 62 | 0,0 | 1,65 |
| T1 | A0.1 | 100,0 | 52,8 | 68,9 / 73,0 / 75,4 | 76,8 | 0,3 / 204,7 | 433 / 659 | 0,0 | 1,03 |
| T1 | A0.1_A1 | 100,0 | 53,4 | 71,7 / 75,9 / 78,2 | 71,8 | 0,3 / 181,9 | 456 / 670 | 0,0 | 1,02 |
| T1 | A0.3 | 100,0 | 41,3 | 49,0 / 52,3 / 55,9 | 84,6 | 2,2 / 68,7 | 168 / 228 | 0,0 | 5,48 |
| T1 | A0.3_A1 | 100,0 | 41,9 | 49,6 / 52,8 / 56,4 | 86,8 | 1,9 / 70,3 | 185 / 270 | 0,0 | 5,26 |
| C6 | A0.1 | 14,3 | 2,5 | 4,0 / 4,8 / 5,9 | 10,4 | 12,0 / 50,8 | 839 / 893 | 0,0 | 0,07 |
| C6 | A0.1_A1 | 100,0 | 17,9 | 29,4 / 32,5 / 35,8 | 61,0 | 35,7 / 268,5 | 548 / 649 | 1,5 | 0,47 |
| C6 | A0.3 | 100,0 | 4,9 | 9,1 / 11,2 / 15,2 | 36,3 | 60,3 / 188,7 | 307 / 398 | 0,0 | 4,39 |
| C6 | A0.3_A1 | 100,0 | 13,7 | 19,0 / 21,7 / 25,5 | 54,4 | 25,8 / 85,8 | 192 / 271 | 0,0 | 4,76 |
| C7 | A0.1 | 23,8 | 6,9 | 7,8 / 8,8 / 10,0 | 19,4 | 17,0 / 118,2 | 853 / 899 | 0,0 | 0,33 |
| C7 | A0.1_A1 | 100,0 | 26,6 | 31,1 / 34,7 / 39,3 | 64,3 | 38,9 / 350,9 | 625 / 670 | 0,5 | 1,18 |
| C7 | A0.3 | 100,0 | 19,9 | 21,4 / 24,5 / 29,5 | 82,9 | 19,7 / 62,2 | 104 / 141 | 0,0 | 5,78 |
| C7 | A0.3_A1 | 100,0 | 19,9 | 21,8 / 24,5 / 28,6 | 77,4 | 20,0 / 103,2 | 162 / 194 | 0,0 | 5,85 |
| C8 | A0.1 | 13,4 | 8,2 | 8,4 / 9,1 / 10,1 | 13,1 | 0,3 / 20,9 | 1226 / 1358 | 0,0 | 0,36 |
| C8 | A0.1_A1 | 100,0 | 45,3 | 62,7 / 67,9 / 72,3 | 64,1 | 0,5 / 513,7 | 931 / 1102 | 0,0 | 0,54 |
| C8 | A0.3 | 100,0 | 12,3 | 14,9 / 16,9 / 19,4 | 48,9 | 83,5 / 289,5 | 454 / 540 | 0,0 | 4,51 |
| C8 | A0.3_A1 | 100,0 | 24,1 | 28,3 / 32,0 / 37,3 | 66,8 | 16,1 / 82,4 | 173 / 232 | 0,0 | 5,42 |
| T3 | A0.1 | 12,9 | 1,5 | 2,0 / 2,6 / 3,9 | 11,6 | 26,5 / 51,5 | 880 / 898 | 0,0 | 0,10 |
| T3 | A0.1_A1 | 100,0 | 36,8 | 39,5 / 42,5 / 46,1 | 71,6 | 32,9 / 318,2 | 622 / 664 | 0,5 | 0,67 |
| T3 | A0.3 | 100,0 | 21,5 | 23,8 / 27,7 / 32,1 | 73,5 | 19,1 / 84,5 | 184 / 234 | 0,0 | 5,71 |
| T3 | A0.3_A1 | 100,0 | 13,3 | 15,3 / 17,9 / 23,2 | 58,7 | 31,5 / 107,8 | 225 / 332 | 0,0 | 5,39 |
| C10 | A0.1 | 1,8 | 1,2 | 1,3 / 1,5 / 1,6 | 1,8 | 0,4 / 5,1 | 884 / 897 | 0,0 | 0,13 |
| C10 | A0.1_A1 | 100,0 | 46,9 | 58,4 / 63,7 / 67,3 | 61,9 | 0,5 / 453,8 | 621 / 653 | 0,5 | 0,27 |
| C10 | A0.3 | 100,0 | 21,7 | 25,0 / 28,8 / 32,6 | 66,8 | 22,4 / 225,6 | 623 / 665 | 0,0 | 4,89 |
| C10 | A0.3_A1 | 100,0 | 37,4 | 39,1 / 43,5 / 49,1 | 79,5 | 5,4 / 233,7 | 601 / 649 | 0,0 | 5,29 |

**Diferença pareada com A1 − sem A1** (média [IC 95%]; `*` = IC exclui 0; SLO e atendidas: + é melhor; tempos: − é melhor)

| Base | Carga | Jobs | Atendidas (pp) | Comb. 1 s (pp) | TTFT 2 s (pp) | TPOT 100 ms (pp) | TTFT p90 (s) | Espera p99 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0.1 | C3 | 5 | 77,9* [38,9; 97,7] | 46,2* [29,4; 60,9] | 56,7* [30,1; 71,5] | 67,6* [39,2; 88,5] | 176,9* [82,8; 227,2] | -200,7* [-252,1; -103,2] |
| A0.1 | C1n8 | 5 | 97,6* [97,4; 97,8] | 56,2* [39,5; 70,9] | 77,9* [74,1; 81,1] | 76,2* [58,9; 89,5] | 166,2* [157,0; 175,3] | -246,0* [-252,9; -237,2] |
| A0.1 | C1n14 | 5 | 49,2* [24,6; 73,9] | -3,0 [-6,0; 1,3] | -1,7 [-4,7; 1,1] | 25,2* [13,9; 36,4] | 372,7* [342,2; 405,8] | -22,1* [-43,3; -3,9] |
| A0.1 | C2 | 5 | 0,0 [0,0; 0,0] | 5,7 [-3,9; 15,2] | 9,2* [0,4; 18,6] | -4,6 [-20,1; 11,0] | -12,1 [-30,6; 2,5] | -12,2 [-36,9; 4,7] |
| A0.1 | T1 | 5 | 0,0 [0,0; 0,0] | 0,5 [-10,6; 11,7] | 2,9 [-2,3; 8,7] | -5,0 [-20,1; 10,0] | -22,8 [-63,3; 16,5] | 22,6 [-7,8; 62,3] |
| A0.1 | C6 | 2 | 85,7* [83,6; 87,8] | 15,4* [9,2; 21,6] | 27,7* [21,0; 34,4] | 50,6* [45,8; 55,5] | 217,6* [201,2; 234,1] | -290,6* [-306,0; -275,3] |
| A0.1 | C7 | 2 | 76,2* [73,7; 78,6] | 19,7* [13,4; 26,0] | 25,9* [16,4; 35,4] | 44,9* [42,4; 47,3] | 232,7* [193,6; 271,8] | -227,8* [-242,0; -213,6] |
| A0.1 | C8 | 2 | 86,6* [82,9; 90,3] | 37,1* [35,9; 38,2] | 58,8* [55,8; 61,9] | 51,0* [37,2; 64,7] | 492,8* [486,3; 499,3] | -295,1* [-325,0; -265,2] |
| A0.1 | T3 | 2 | 87,1* [83,6; 90,7] | 35,2* [22,1; 48,4] | 39,9* [23,0; 56,8] | 60,0* [52,0; 68,0] | 266,7* [211,7; 321,7] | -258,2* [-272,3; -244,1] |
| A0.1 | C10 | 2 | 98,2* [98,0; 98,4] | 45,7* [42,7; 48,7] | 62,2* [61,3; 63,1] | 60,1* [52,6; 67,6] | 448,7* [446,6; 450,8] | -263,2* [-263,5; -262,8] |
| A0.3 | C3 | 5 | 0,0 [0,0; 0,0] | -0,4 [-13,6; 12,0] | 1,1 [-11,7; 13,9] | -5,0 [-14,1; 7,4] | 26,0 [-15,3; 59,6] | 86,2* [6,1; 172,0] |
| A0.3 | C1n8 | 5 | 0,0 [0,0; 0,0] | -4,0 [-10,3; 5,6] | -6,0 [-13,7; 4,1] | 7,4* [1,7; 12,0] | 1,9 [-14,5; 18,2] | 3,6 [-29,6; 42,5] |
| A0.3 | C1n14 | 5 | -3,1 [-9,2; 0,0] | -0,6 [-2,0; 0,5] | 0,2 [-1,1; 1,5] | -6,9 [-17,6; 2,4] | 18,2 [-71,1; 91,2] | 43,8 [-91,8; 157,1] |
| A0.3 | C2 | 5 | 0,0 [0,0; 0,0] | 0,0 [-20,0; 24,7] | 5,1 [-6,1; 18,0] | -2,5 [-24,2; 21,0] | -9,2 [-29,4; 9,1] | -13,1 [-39,6; 11,9] |
| A0.3 | T1 | 5 | 0,0 [0,0; 0,0] | 0,6 [-6,5; 10,5] | 0,5 [-4,4; 6,0] | 2,1 [-2,9; 9,7] | 1,6 [-14,8; 18,1] | 16,3 [-38,5; 71,1] |
| A0.3 | C6 | 2 | 0,0 [0,0; 0,0] | 8,8* [3,9; 13,7] | 10,4* [8,1; 12,7] | 18,1* [12,6; 23,7] | -102,9* [-176,6; -29,2] | -114,7* [-167,0; -62,3] |
| A0.3 | C7 | 2 | 0,0 [0,0; 0,0] | -0,1 [-0,3; 0,2] | -0,0 [-0,8; 0,7] | -5,5* [-8,4; -2,7] | 41,0 [-0,2; 82,2] | 58,5 [-11,7; 128,8] |
| A0.3 | C8 | 2 | 0,0 [0,0; 0,0] | 11,8* [8,1; 15,5] | 15,1* [8,7; 21,5] | 17,9* [6,7; 29,0] | -207,1 [-424,9; 10,7] | -280,7* [-492,4; -69,1] |
| A0.3 | T3 | 2 | 0,0 [0,0; 0,0] | -8,2* [-11,4; -5,0] | -9,9* [-15,7; -4,1] | -14,8* [-15,2; -14,4] | 23,3* [14,0; 32,6] | 41,9* [37,1; 46,8] |
| A0.3 | C10 | 2 | 0,0 [0,0; 0,0] | 15,7* [15,6; 15,7] | 14,7* [14,5; 15,0] | 12,7* [12,6; 12,7] | 8,0 [-13,3; 29,3] | -22,2* [-31,0; -13,4] |

**Leitura.**
- **Impasses (H1, H2):** sem A1, a A0.1 trava em 24 de 25 níveis das cargas de impasse (C3 4/5; C1n8, C1n14 5/5; C6,
  C7, C8, T3, C10 todos). Com A1, **nenhum** nível trava, com A0.1 nem com A0.3: 0 de 70. O detector disparou em
  média 2,2 vezes por nível no C1n14, 1,5 no C6 e 0,5 no C7, no T3 e no C10: a A1.1 sozinha não basta (H2).
  - A A0.3 (troca sem drenagem, folga de 3 GB) não travou em nenhum nível, com ou sem A1.
- **Ganho da A1 sobre a A0.1** nas cargas de impasse: de +49 a +98 pontos de atendidas; de +15 a +56 pontos no SLO
  combinado (exceto C1n14); espera p99 de 200 a 300 s menor. O TTFT p90 sobe porque as requisições que antes ficavam
  sem resposta (fora do percentil, que é das atendidas) agora são atendidas tarde; a espera p99, que conta as não
  atendidas, cai.
- **C1n14 com A0.1 + A1:** atende +49 pontos, mas o SLO combinado não muda (−3,0, IC inclui 0): fome da A0.1 (H4,
  anomalia 1).
- **C10 (tamanhos 3B–32B):** com A0.1, de 1,8% para 100% atendidas e de 1,2% para 46,9% no combinado; com A0.3, +16
  pontos no combinado. É a carga em que a A1 mais ajuda a A0.3: os modelos grandes são os que mais precisam de KV.
- **Controles (H3):** no C2 e no T1, nenhuma vista piora com significância, com A0.1 nem com A0.3. No C2 com A0.1, o
  só TTFT a 2 s melhora 9 pontos.
- **Com A0.3 (folga 3 GB + A1), efeito misto:** melhora no C6 (+9), no C8 (+12) e no C10 (+16); piora no T3 (−8
  combinado, −15 TPOT), espera p99 +86 s no C3, TPOT −5,5 no C7. Ver anomalia 4 e a verificação da folga.

### Verificação da folga (A0.4, D37)

**Impasses (níveis com T1 ≥ 100 s / níveis VALIDA)**

| Carga | A0.1 | A0.1_A1 | A0.3 | A0.3_A1 | A0.3_A1h0 |
| --- | --- | --- | --- | --- | --- |
| C3 | – | – | 0/2 | 0/2 | 0/2 |
| C6 | – | – | 0/2 | 0/2 | 0/2 |
| C7 | – | – | 0/2 | 0/2 | 0/2 |
| T3 | – | – | 0/2 | 0/2 | 0/2 |

**Médias por braço** (S1; frações sobre todas as enviadas, em %; tempos em s)

| Carga | Braço | Atendidas | Comb. 1 s | TTFT 1 / 2 / 5 s | TPOT 100 ms | TTFT p50 / p90 | Espera p99 / máx. | Disparos A1.2 | Ativações/min |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C3 | A0.3 | 100,0 | 14,8 | 16,8 / 21,4 / 25,4 | 75,0 | 27,2 / 111,2 | 165 / 176 | 0,0 | 6,42 |
| C3 | A0.3_A1 | 100,0 | 23,1 | 26,3 / 30,5 / 34,2 | 86,2 | 22,8 / 72,1 | 114 / 135 | 0,0 | 6,18 |
| C3 | A0.3_A1h0 | 100,0 | 16,4 | 23,0 / 29,1 / 34,1 | 68,5 | 22,0 / 81,7 | 132 / 153 | 0,0 | 6,40 |
| C6 | A0.3 | 100,0 | 25,6 | 28,2 / 31,7 / 36,9 | 72,6 | 15,5 / 71,3 | 136 / 236 | 0,0 | 5,35 |
| C6 | A0.3_A1 | 100,0 | 27,6 | 31,3 / 34,4 / 38,9 | 69,2 | 16,0 / 62,1 | 141 / 179 | 0,0 | 5,36 |
| C6 | A0.3_A1h0 | 100,0 | 23,4 | 27,7 / 31,7 / 36,8 | 71,7 | 15,2 / 68,9 | 160 / 262 | 0,0 | 5,59 |
| C7 | A0.3 | 100,0 | 15,6 | 17,5 / 20,3 / 26,5 | 73,8 | 25,1 / 79,7 | 182 / 198 | 0,0 | 5,41 |
| C7 | A0.3_A1 | 100,0 | 9,8 | 14,1 / 16,7 / 20,7 | 58,0 | 34,8 / 100,2 | 159 / 226 | 0,0 | 5,07 |
| C7 | A0.3_A1h0 | 100,0 | 17,8 | 21,0 / 24,3 / 29,3 | 68,3 | 25,7 / 81,5 | 143 / 173 | 0,0 | 5,60 |
| T3 | A0.3 | 100,0 | 10,3 | 14,5 / 17,0 / 22,0 | 52,2 | 35,3 / 132,6 | 281 / 352 | 0,0 | 5,29 |
| T3 | A0.3_A1 | 100,0 | 16,8 | 19,0 / 21,5 / 26,4 | 72,1 | 26,9 / 85,6 | 184 / 235 | 0,0 | 5,93 |
| T3 | A0.3_A1h0 | 100,0 | 13,8 | 18,9 / 21,2 / 28,1 | 56,3 | 22,1 / 88,5 | 234 / 290 | 0,0 | 5,39 |

**Diferença pareada com A1 − sem A1** (média [IC 95%]; `*` = IC exclui 0; SLO e atendidas: + é melhor; tempos: − é melhor)

| Base | Carga | Jobs | Atendidas (pp) | Comb. 1 s (pp) | TTFT 2 s (pp) | TPOT 100 ms (pp) | TTFT p90 (s) | Espera p99 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0.3 | C3 | 2 | 0,0 [0,0; 0,0] | 8,4 [-0,9; 17,7] | 9,1 [0,0; 18,2] | 11,3* [10,4; 12,2] | -39,1* [-54,0; -24,3] | -50,6* [-69,0; -32,2] |
| A0.3 | C6 | 2 | 0,0 [0,0; 0,0] | 2,0* [0,3; 3,8] | 2,7* [2,5; 2,8] | -3,4 [-7,1; 0,4] | -9,2* [-15,9; -2,5] | 4,9* [4,2; 5,6] |
| A0.3 | C7 | 2 | 0,0 [0,0; 0,0] | -5,8* [-7,2; -4,4] | -3,5* [-4,6; -2,5] | -15,8* [-22,0; -9,5] | 20,5* [18,3; 22,7] | -23,5* [-39,2; -7,9] |
| A0.3 | T3 | 2 | 0,0 [0,0; 0,0] | 6,5 [-1,1; 14,1] | 4,4 [-3,2; 12,0] | 19,9* [4,2; 35,5] | -47,0* [-70,8; -23,2] | -97,1 [-214,1; 20,0] |
| A0.3 (A1 com folga 0) | C3 | 2 | 0,0 [0,0; 0,0] | 1,6 [-3,1; 6,4] | 7,7* [6,0; 9,3] | -6,5 [-15,3; 2,4] | -29,6* [-58,5; -0,7] | -33,3* [-54,1; -12,5] |
| A0.3 (A1 com folga 0) | C6 | 2 | 0,0 [0,0; 0,0] | -2,2 [-22,7; 18,4] | 0,0 [-17,7; 17,7] | -0,9 [-31,3; 29,5] | -2,5 [-42,6; 37,7] | 24,4 [-55,4; 104,3] |
| A0.3 (A1 com folga 0) | C7 | 2 | 0,0 [0,0; 0,0] | 2,2 [-9,8; 14,1] | 4,1 [-8,3; 16,4] | -5,5 [-37,7; 26,7] | 1,8 [-48,9; 52,4] | -39,6 [-148,3; 69,0] |
| A0.3 (A1 com folga 0) | T3 | 2 | 0,0 [0,0; 0,0] | 3,5* [1,1; 5,9] | 4,1 [-0,8; 9,0] | 4,1* [2,2; 5,9] | -44,0* [-60,5; -27,6] | -47,8* [-70,1; -25,6] |
| folga 0 × folga 3 (com A1) | C3 | 2 | 0,0 [0,0; 0,0] | -6,7 [-20,8; 7,3] | -1,5 [-12,2; 9,3] | -17,8* [-27,5; -8,0] | 9,6 [-4,5; 23,7] | 17,3 [-21,9; 56,5] |
| folga 0 × folga 3 (com A1) | C6 | 2 | 0,0 [0,0; 0,0] | -4,2 [-26,5; 18,1] | -2,7 [-20,5; 15,2] | 2,5 [-31,7; 36,6] | 6,7 [-26,8; 40,2] | 19,5 [-61,0; 100,0] |
| folga 0 × folga 3 (com A1) | C7 | 2 | 0,0 [0,0; 0,0] | 8,0 [-2,5; 18,5] | 7,6 [-5,8; 21,0] | 10,3 [-15,7; 36,3] | -18,7 [-71,6; 34,1] | -16,1 [-109,1; 76,8] |
| folga 0 × folga 3 (com A1) | T3 | 2 | 0,0 [0,0; 0,0] | -3,0 [-13,0; 7,0] | -0,3 [-12,8; 12,2] | -15,8 [-33,2; 1,7] | 3,0 [-37,3; 43,2] | 49,2 [-90,1; 188,5] |

**Leitura.**
- **A piora do T3 não se repetiu.** Nesta janela, a A0.3 + A1 com folga 3 GB fica **acima** da A0.3 no T3 (+6,5
  combinado, +20 TPOT), contra −8,2 na campanha da véspera. O mesmo braço da A0.3 deu 21,5% de combinado no T3 na
  campanha e 10,3% aqui: deriva do nó (regra 3) e variância entre repetições grandes. Com 2 repetições, o "IC exclui
  0" da campanha no T3 era fraco.
- **A A0.3 + A1 com folga 3 GB piora o C7 de novo** (−5,8 combinado, −15,8 TPOT; mesmo sinal nas 4 repetições das duas
  rodadas). No C3, desta vez melhora (+8,4, TPOT +11).
- **Com folga 0 (A0.4 candidata), nenhuma vista piora com significância em relação à A0.3** nas quatro cargas; T3
  melhora (+3,5 combinado, TTFT p90 −44 s), C3 melhora no TTFT a 2 s (+7,7) e na cauda (espera p99 −33 s).
- **Folga 0 × folga 3, os dois com A1:** nenhuma diferença significativa no combinado; o TPOT do C3 fica pior com
  folga 0 (−17,8).
- **Memória ociosa:** a memória livre mediana do controlador é ~15 GB com a A0.3, 23–25 GB com A1 e folga 3, e 20–22 GB
  com A1 e folga 0. A soma folga + piso deixa ~3 GB a mais parados, como previsto; o número de residentes, porém,
  varia muito entre repetições (a própria A0.3 vai de 3,1 a 5,8 no C7), e o efeito "um residente a menos" da anomalia 4
  não se confirmou de forma consistente.

Figuras (`polyaxon/f4_figs.py`, `reports/figs/F04/`): linha do tempo de memória da GPU, memória livre vista pelo
controlador e estado e respostas de cada modelo, para o mesmo job sem e com A1:
- `f4-c6-1_A0.1.png` × `f4-c6-1_A0.1_A1.png`: sem A1, nada mais conclui depois de ~245 s (GPU em 133 de 140 GB, livre
  abaixo do piso); com A1, o detector despeja o `model_3` em ~185 s e o serviço segue até o fim da janela; os modelos
  7, 9 e 10 só entram depois da janela (fome da A0.1);
- `f4-c1n8-1_A0.1.png` × `f4-c1n8-1_A0.1_A1.png`; `f4-c1n14-1_A0.1_A1.png` (disparos do detector e fome);
- `f4-t3-1_A0.3.png` × `f4-t3-1_A0.3_A1.png` (anomalia 4).

## Anomalias e investigações

**1. C1n14 com A0.1 + A1 atende 57–66%, sem melhorar o SLO combinado.** Linha do tempo do log de decisões (smoke e
campanha):
- com a A1.1, a ativação exige `15 + 1 + 7,2 = 23,2 GB` livres; o controlador fica com 7 residentes, e a memória livre
  estaciona em ~7,1 GB, o piso: o KV dos residentes cresce até ele;
- em t ≈ 200 s do smoke há 120 requisições esperando nos residentes, nenhuma rodando, memória no piso, nenhuma
  conclusão há 35 s: a assinatura do T1, mesmo com a A1.1 (H2). O detector despejou um residente com preempção em
  30 s. T1 dos níveis: 34 s no smoke, média de 30 s na campanha, sempre muito abaixo de 100 s;
- os modelos 12–14 esperam o nível inteiro: os 7 residentes sempre têm fila, nunca ficam 50 s ociosos, e a A0.1 não
  despeja modelo ocupado. É a fome vista na F1.3 (H4), não um impasse.
- Classificação: comportamento da política A0.1, esperado. Nenhuma correção na F4; é o caso das políticas da F6.

**2. P15 (nova): o worker do Qwen2.5-14B/32B morre no prefill (C10, 6 de 8 níveis INVALIDA_SISTEMA por V2).**
- Sintoma: `RuntimeError: Failed to allocate memory for batch_prefill_tmp_v with size 437–468 MB ... in AlignedAllocator`
  no `plan` do prefill paginado do flashinfer, sempre no `model_7`/`model_8` (14B, 32B), num pedaço de 8192 tokens.
- Causa: o *workspace* do flashinfer é fixo em 384 MB por worker (`global_config.flashinfer_workspace_size`); os
  temporários da divisão de KV desses modelos passam disso. Não é falta de memória da GPU, e acontece com e sem A1;
  as duas A0.1 sem A1 escaparam só porque travaram em 25 s.
- Correção: 512 MB para `Qwen2ForCausalLM`, como as versões seguintes do SGLang (`flashinfer_backend.py`,
  `PRISM_FLASHINFER_WS_QWEN2_MB`); nenhuma carga anterior usa Qwen. Registrada em `reports/erros.md`.
- **Verificação:** jobs `f4-c10-1b`, `f4-c10-2b`: 8 de 8 VALIDA, nenhum `AlignedAllocator`. Resolvida.

**3. V13 contava as ativações pendentes como erro de medição (`f4-c1n14-3` A0.3_A1).**
- O V13 compara a memória livre do controlador com a do `nvidia-smi`, mas lia a linha `GPU 0, mem X` do log, que é a
  memória **disponível** (livre − ativações pendentes, R2.1). Nesse nível as ativações demoraram (p90 de 37,5 s; houve
  ativação pendente em 61 de 117 ciclos), e a mediana da diferença deu 16,6 GB, contra 0,68 GB com a memória livre de
  fato (`free_gb` do log de decisões).
- Classificação: erro de medição do validador (seção 0.3, item 4). Correção em `polyaxon/validate_run.py`: soma de
  volta o `pending_gb` do ciclo correspondente do log de decisões (pareado por tempo). O critério do V13 (2 GB) não
  mudou (D36).
- Verificação: revalidei todos os jobs da F4 e os da F3 e da F6a com o validador corrigido; só esse nível muda de
  classificação. Os CSVs da F3 e da F6a não foram sobrescritos.

**4. Com a A0.3, a A1 com folga de 3 GB piora o T3 na campanha (−8 combinado, −15 TPOT; 2 de 2 repetições).**
- Hipótese: a folga de 3 GB da A0.3 (`PRISM_ACTIVATION_HEADROOM_GB`) e o piso de 7,2 GB da A1.1 se somam (~26 GB
  exigidos por ativação de um 8B), o que tira residência.
- Teste (verificação da folga, D37): a soma deixa de fato ~3 GB a mais parados, mas a piora do T3 **não se repetiu**
  (+6,5 nesta janela). O C7 piorou de novo com folga 3 GB (4 de 4 repetições), e não piora com folga 0.
- Conclusão: a soma folga + piso é um custo sem função (as duas reservam KV); com folga 0, nenhuma das quatro cargas
  piora em relação à A0.3. A variância entre janelas é grande, e 2 repetições não separam efeitos de ~5 pontos.

## Critérios de aceitação

| Critério | Situação | Evidência |
| --- | --- | --- |
| Testes unitários cobrindo os estados do impasse observados | **OK** | `tests/policy/test_structural.py` (27 testes) |
| Zero impasses (T1 ≥ 100 s, D37) em C3 e C1 (8 e 14 modelos) com A0.1 + A1 e A0.3 + A1, 5 repetições | **OK** (0 de 30) | tabela de impasses; `reports/data/F04/campanha/niveis.csv` |
| Zero impasses nas cargas da D29 com A1 | **OK** (0 de 20: C6, C7, C8, T3, C10) | idem |
| Nenhuma piora significativa nos cenários sem impasse, leitura (b) por braço (D37) | **OK com A0.1 + A1; com A0.3 + A1 só com folga 0 e só nas cargas testadas** (abaixo) | tabelas pareadas |
| `b`, `Δ_imp`, `T_min` registrados | **OK** | D34 |

**Critério de piora, leitura (b):**
- **A0.1 + A1 × A0.1:** todo braço da A0.1 sem impasse é C2 ou T1, e nenhuma vista piora. **OK.**
- **A0.3 + A1 com folga 3 GB × A0.3** (o braço da campanha): **FALHA** no C7 (4 de 4 repetições), no C3 (cauda, na
  campanha) e no T3 (na campanha; não se repetiu).
- **A0.3 + A1 com folga 0 × A0.3** (A0.4, D37): **OK nas quatro cargas em que a folga 3 GB falhou ou tinha ganho**
  (T3, C3, C7, C6; 2 repetições). **Não testado** nas outras seis (C1n8, C1n14, C2, T1, C8, C10), em que a versão com
  folga 3 GB não piorou nada.

## Decisão do gate: APROVADO (Gabriel, 2026-11-06, D38)

Opção (i): aprovado com a A0.4 verificada em T3, C3, C7 e C6 e a lacuna declarada; as outras seis cargas recebem a
A0.4 na campanha da F5. Respostas anteriores do Gabriel: impasse = T1 ≥ 100 s, leitura (b) do critério de piora,
A0.4 com folga 0 (D37).

Texto da revisão (como estava antes da decisão):

Pela leitura (b), o gate passa para a A0.1 + A1 e para a A0.4 (A0.3 + A1 com folga 0) nas cargas testadas. Falta uma
decisão do Gabriel:
- **(i)** aprovar com a A0.4 = folga 0 verificada em T3, C3, C7, C6, e a lacuna declarada (as outras seis cargas
  entram na F5, que roda a A0.4 em todas as cargas de qualquer forma); ou
- **(ii)** rodar a A0.4 nas outras seis cargas antes do gate (6 jobs com {A0.3, A0.4} × 2 repetições, ~3 h com 3
  slots).

## Pendências que passam para fases seguintes

- **A0.4 = A0.3 + A1 com `PRISM_ACTIVATION_HEADROOM_GB=0`** (D37); a A0.3 com folga de 3 GB fica só como referência
  histórica. A F5 roda a A0.4 em todas as cargas.
- **Fome da A0.1 (F6):** C1n14 e os modelos que só entram depois da janela (C6, C7, T3) são o caso da A2.3/A3/A10.
- **A0.3 sem drenagem é fraca em várias cargas** (C3: 18,6% contra 58,1% da A0.1 + A1; C6, C8): ~6 ativações/min.
  Vai para a F5 (linhas de base) e para a F6.0.
- **Variância entre janelas:** o mesmo braço da A0.3 deu 21,5% e 10,3% no T3 em dias seguidos. Comparações de ~5
  pontos pedem mais de 2 repetições (C-V1/C-V2 da F5).
- **V13 corrigido (D36):** campanhas futuras usam o validador novo; nenhuma classificação anterior mudou.
- **Reserva de KV contínua (ideia, não plano):** a A1.1 só reserva na ativação, e o KV dos residentes volta ao piso
  (anomalia 1); uma reserva mantida o tempo todo evitaria até os travamentos curtos que a A1.2 quebra.

## Reprodução

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
# calibração (sem jobs)
$PY polyaxon/f4_calib.py /mnt/scratch/scheduler/prism-raw/F3-dry /mnt/scratch/scheduler/prism-raw/F6a-tri /mnt/scratch/scheduler/prism-raw/F6a --out reports/data/F04/calib/calib_niveis.tsv
# smoke
PRISM_JOB_SUFFIX=-f4-smoke PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f4_smoke_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
/mnt/scratch/scheduler/polyax-env/bin/polyaxon ops artifacts -p kunumi/hpc4ai -uid cbb45bf8766d4eb6b5cb71afc8c12d27 -d outputs --path /mnt/scratch/scheduler/prism-raw/F4/smoke
python3 polyaxon/validate_run.py --csv reports/data/F04/validador/smoke.csv /mnt/scratch/scheduler/prism-raw/F4/smoke
# campanha: suítes, driver (retomável), análise
bash polyaxon/f4_suites.sh
bash polyaxon/f4_driver_start.sh        # log em reports/data/F04/driver.log
$PY polyaxon/f4_report_tables.py reports/data/F04/campanha      # tabelas deste relatório
$PY polyaxon/f4_figs.py reports/data/F04/campanha reports/figs/F04
# reexecução do C10 com a correção da P15 (flashinfer_backend.py, PRISM_FLASHINFER_WS_QWEN2_MB=512)
PRISM_JOB_SUFFIX=-f4-c10-1b PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f4_camp_C10_a_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f4-c10-2b PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f4_camp_C10_b_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh
# análise da campanha com os jobs do C10 refeitos (sem f4-c10-1/2, que rodaram antes da P15)
$PY polyaxon/f4_analysis.py reports/data/F04/campanha $(ls reports/data/F04/validador/f4-*.csv | grep -v "folga\|f4-c10-1.csv\|f4-c10-2.csv")
# verificação da folga (D37): suítes, fila e driver; análise
bash polyaxon/f4_folga_suites.sh
bash polyaxon/f4_driver_start.sh folga  # log em reports/data/F04/driver_folga.log
$PY polyaxon/f4_analysis.py reports/data/F04/folga reports/data/F04/validador/f4-folga-*.csv
$PY polyaxon/f4_report_tables.py reports/data/F04/folga
```

Versões do código: `reports/data/F04/codigo/f4_smoke.diff` (smoke), `f4_camp.diff` (campanha), `f4_c10b.diff`
(reexecução do C10, com a P15), cada um com o `.sha256`; base `d6afc63`.
