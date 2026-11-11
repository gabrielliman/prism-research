# F06.15 — Confirmação das políticas por prazo e por atraso virtual, 5 repetições (2026-11-11)

Data: campanha de 2026-11-10 10:12 UTC a 2026-11-11 12:18 UTC; análise em 2026-11-11. Branch `scheduling-research`.
Suítes e driver: `b9348dd` (suítes), `442c8a3` (driver limpa o destino antes de cada download). Análise: `5c27ebb`
(`f615_compare.py`), `4b59136` (D56, TPOT como no artigo do Prism), `1706e53` (resultados) e o commit deste relatório
(`f615_decomp.py`, `f615_report_tables.py`). **Código do servidor e da política nos 300 níveis: o de `b9348dd`, anterior à
D59** (verificado nos logs, ver "Anomalias").

Glossário:
- **A0.2+A1** = despejo por ociosidade de 10 s, com as restrições estruturais A1 (reserva de KV, quebra de impasse em
  30 s, residência mínima de 10 s);
- **A0.4** = troca por throughput/GB, sem preempção, com A1;
- **A9.2** = VLT ciente da residência, sem preempção. VLT é o atraso virtual do SuperInfer: entra o modelo cujas
  requisições esperaram mais, descontado o custo medido da troca;
- **A9.4 (λ = 1)** = A9.2 decidindo a cada troca se preempta a vítima ocupada (preempta se as requisições salvas forem
  ≥ as perdidas);
- **A2.1** = EDF entre modelos (entra o modelo com o prazo viável mais cedo), sem preempção e, no S6 `k_R`=4, também com
  preempção global;
- **S3 `k_A`=5** = prazo de TTFT de 5× o custo de ativação (~7 s num 8B);
- **S6 `k_R`** = prazo de `k_R` trocas reais sem preempção (~16, ~31 e ~63 s num 8B; `reports/registro/latencia_ref.md`,
  `c_rot.json`);
- **pior quarto** = fração no prazo dos 25% piores modelos;
- **Jain** = índice de justiça entre modelos (1 = todos iguais).

## Objetivo

Confirmar com 5 repetições, sob o objetivo da D52 (justiça entre modelos sem grande perda de SLO total), o que a F6.0
e a triagem F6.16 indicaram (D54). As perguntas:
- a A9.2 é mais justa que a A0.4 no prazo curto, sem perder total?
- a A9.4 com λ = 1 melhora a A9.2?
- onde a A2.1 fica?
- a preempção ajuda a A2.1 com prazo folgado?

## Hipóteses

- **H1:** no S3 `k_A`=5 a A9.2 tem pior quarto e Jain maiores que a A0.4 (triagem: +5,5\*, +5,3\*), sem perda
  significativa de total.
- **H2:** a A9.4 com λ = 1 preempta mais que com λ = 3 (triagem: 4% das trocas com vítima ocupada) e melhora a justiça
  da A9.2 no prazo curto.
- **H3:** nos prazos de ≥ 2 trocas, a A0.4 é tão justa quanto as variantes do VLT e tem mais total (F6.16).
- **H4:** a A2.1 com preempção no S6 `k_R`=4 não melhora a A2.1 sem preempção (F6.0: a preempção não ajudou).

## Mudanças de código (arquivo, função, variável de ambiente, padrão)

| Arquivo | Mudança | Variável / padrão |
| --- | --- | --- |
| `polyaxon/f6_15_suites.sh`, `configs/f615_*_suite.tsv`, `configs/f615_queue.tsv` | suítes: 4 cargas × 5 repetições × 15 níveis | — |
| `polyaxon/f4_driver.py`, `f4_driver_start.sh f615` | modo `f615`; limpa o destino antes de cada download (`442c8a3`) | `F4_QUEUE`, `F4_STATE`, `F4_TIMEOUT=28800` |
| `polyaxon/slo_metrics.py`, `f60_analysis.py` | família S1D (TPOT = `k_D` × P95 dedicado, como no artigo do Prism; D56) e níveis S6 `k_R`=2 | `S1D:ttft=1,kD=2`, `S1D:ttft=1,kD=5` |
| `polyaxon/f615_compare.py` | tabelas por política e diferenças pareadas com bootstrap estratificado por carga; tabela padrão | — |
| `polyaxon/f615_decomp.py` | decomposição das violações (inevitável/evitável) por braço no seu nível | — |
| `polyaxon/f615_report_tables.py` | tabelas deste relatório (`analise/tabelas.md`) | — |

Nenhuma mudança em `python/` (servidor, controlador, política) durante a campanha.

## Configurações executadas

Por job (uma carga × uma repetição, todos os braços na mesma janela, regra 3), 15 níveis:
- linhas de base A0.2+A1 e A0.4 (avaliadas depois em todos os prazos);
- A9.2 (`lvfr_*_p0`), A2.1 (`edf_*_p0`) e A9.4 (`lvfp_*_ps`) em S3 `k_A`=5 e S6 `k_R` = 1, 2 e 4;
- A2.1 com preempção em S6 `k_R`=4 (`edf_S6k4_p1`).

O prazo enviado ao gerador é o do nível (`PRISM_OVL_SLO_SPEC`); o TPOT de todos os níveis é `k_D` = 5 × P95 dedicado.

Variáveis comuns: `PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10` e, fora a A0.2+A1,
`PRISM_ACTIVATION_HEADROOM_GB=0`. Por braço:
- A0.2+A1: `PRISM_IDLE_THRESHOLD=10`;
- A0.4: `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0`;
- A9.2: `PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_SWAP_PREEMPT=0`;
- A9.4: a mesma da A9.2 + `PRISM_LVF_PREEMPT=per_swap PRISM_LVF_PREEMPT_LAMBDA=1`;
- A2.1: `PRISM_EVICTION=edf PRISM_SWAP_PREEMPT=0` (ou `=1` no braço com preempção).

| Carga | Passo | Variáveis |
| --- | --- | --- |
| C1, 10 modelos 8B (fome de memória) | `ovl_mem` | `PRISM_OVL_RATES=0.2` |
| T1 (trace do Prism) | `ovl_trace_big` | `PRISM_OVL_RATES=1` |
| C6, 14 modelos (popularidade que muda) | `ovl_zipf` | `PRISM_OVL_RATES=2 PRISM_OVL_N=14` |
| T3 (trace Azure Functions) | `ovl_tr_azfn` | `PRISM_OVL_RATES=1` |

As cargas e a justificativa de relevância são as da F6.0 (`F06_0_repeticao_sem_drenagem.md`): todas forçam trocas, e as
quatro diferem em quem é popular e em como a popularidade muda.

## Execuções

| Job | uuid | Job | uuid |
| --- | --- | --- | --- |
| `f615-c1n10-1` | `5c1dc2d8` | `f615-t1-1` | `a94786da` |
| `f615-c6n14-1` | `4d1a5fa7` | `f615-t3-1` | `681495e1` |
| `f615-c1n10-2` | `f54dfb78` | `f615-t1-2` | `952fb6f2` |
| `f615-c6n14-2` | `c3a18268` | `f615-t3-2` | `f65ab1f7` |
| `f615-c1n10-3` | `da493cde` | `f615-t1-3` | `ea6c674d` |
| `f615-c6n14-3` | `3baba70b` | `f615-t3-3` | `7d4f2fb6` |
| `f615-c1n10-4` | `193a148d` | `f615-t1-4` | `86fc0d55` |
| `f615-c6n14-4` | `017c800f` | `f615-t3-4` | `c2be9106` |
| `f615-c1n10-5` | `8a316540` | `f615-t1-5` | `aea0d929` |
| `f615-c6n14-5` | `31e61442` | `f615-t3-5` | `493cf4f2` |

**300/300 níveis VALIDA, nenhuma reexecução, nenhum K1.** Validador: `reports/data/F06/f615/validador/`. Brutos em
`/mnt/scratch/scheduler/prism-raw/F6/f615/`. Estado do driver: `reports/data/F06/f615/jobs.tsv` e `driver.log`. Duração
de um job: C1 ~3,0 h, T1 ~4,3 h, C6 ~4,4 h, T3 ~4,1 h. Até 3 jobs simultâneos (regra 2).

## Resultados

Médias dos 20 jobs (4 cargas × 5 repetições). Frações sobre todas as enviadas. As diferenças são pareadas no mesmo job,
com IC 95% por bootstrap estratificado por carga (`*` = IC exclui 0). Todas as tabelas estão em
`reports/data/F06/f615/analise/tabelas.md`; o braço − A0.2+A1 está na tabela B3 de lá.

### Tabela P: padrão dos relatórios (CLAUDE.md regra 7, D56; média dos 20 jobs)

TTFT só 1/2/5 s (estrito); TPOT só como no artigo do Prism, `k_D` × P95 dedicado com `k_D` = 2 e 5 (S1D); combinado TTFT < 1 s e TPOT ≤ 5×P95; TPOT 100 ms como referência secundária. Gerada por `polyaxon/f615_compare.py` (`tabela_padrao.md`).

| Configuração | jobs | servidas | TTFT 1 s | TTFT 2 s | TTFT 5 s | TPOT 2×P95 | TPOT 5×P95 | combinado 1 s + 5×P95 | TPOT 100 ms | TTFT p50 / p90 (s) | espera p99 / máx. (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0.2+A1 (ociosidade 10 s) | 20 | 100% | 49% | 54% | 58% | 25% | 87% | 44% | 77% | 5 / 188 | 447 / 520 |
| A0.4 (troca por throughput) | 20 | 100% | 33% | 36% | 40% | 28% | 85% | 29% | 76% | 18 / 79 | 152 / 210 |
| A9.2 (VLT residência) — S3 `k_A`=5 (~7 s) | 20 | 100% | 32% | 35% | 39% | 28% | 83% | 29% | 74% | 24 / 107 | 159 / 181 |
| A2.1 (EDF) — S3 `k_A`=5 (~7 s) | 20 | 100% | 36% | 39% | 44% | 28% | 84% | 32% | 75% | 12 / 117 | 311 / 368 |
| A9.4 (VLT, preempção por troca, λ=1) — S3 `k_A`=5 (~7 s) | 20 | 100% | 31% | 34% | 38% | 29% | 82% | 27% | 73% | 30 / 115 | 174 / 198 |
| A9.2 (VLT residência) — S6 `k_R`=1 (~16 s) | 20 | 100% | 32% | 35% | 38% | 29% | 81% | 30% | 73% | 25 / 111 | 164 / 186 |
| A2.1 (EDF) — S6 `k_R`=1 (~16 s) | 20 | 100% | 34% | 38% | 42% | 25% | 82% | 31% | 73% | 14 / 117 | 267 / 363 |
| A9.4 (VLT, preempção por troca, λ=1) — S6 `k_R`=1 (~16 s) | 20 | 100% | 28% | 31% | 35% | 24% | 79% | 25% | 70% | 29 / 112 | 167 / 201 |
| A9.2 (VLT residência) — S6 `k_R`=2 (~31 s) | 20 | 100% | 31% | 35% | 39% | 24% | 79% | 28% | 68% | 28 / 116 | 175 / 197 |
| A2.1 (EDF) — S6 `k_R`=2 (~31 s) | 20 | 100% | 35% | 38% | 42% | 26% | 86% | 32% | 77% | 14 / 95 | 228 / 323 |
| A9.4 (VLT, preempção por troca, λ=1) — S6 `k_R`=2 (~31 s) | 20 | 100% | 31% | 34% | 38% | 29% | 84% | 28% | 74% | 22 / 101 | 157 / 183 |
| A9.2 (VLT residência) — S6 `k_R`=4 (~63 s) | 20 | 100% | 30% | 33% | 37% | 30% | 82% | 28% | 73% | 26 / 103 | 151 / 166 |
| A2.1 (EDF) — S6 `k_R`=4 (~63 s) | 20 | 100% | 35% | 38% | 41% | 25% | 87% | 32% | 79% | 16 / 88 | 172 / 242 |
| A9.4 (VLT, preempção por troca, λ=1) — S6 `k_R`=4 (~63 s) | 20 | 100% | 29% | 32% | 35% | 27% | 80% | 26% | 71% | 29 / 114 | 169 / 202 |
| A2.1 (EDF) com preempção — S6 `k_R`=4 (~63 s) | 20 | 100% | 27% | 30% | 33% | 36% | 88% | 25% | 81% | 24 / 110 | 248 / 371 |


### Tabela A: total, justiça e caudas por nível (média dos 20 jobs)

| Nível | Política | total | pior quarto | pior modelo | Jain ×100 | TTFT p90 do pior modelo (s) | TTFT p50 / p90 (s) | espera p99 / máx. (s) | rotações | preemptadas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 (~7 s) | A0.2+A1 (ociosidade 10 s) | 61% | 5% | 1% | 66 | 477 | 5 / 188 | 447 / 520 | 0 | 0 |
| S3 `k_A`=5 (~7 s) | A0.4 (troca por throughput) | 42% | 14% | 9% | 80 | 172 | 18 / 79 | 152 / 210 | 51 | 0 |
| S3 `k_A`=5 (~7 s) | A9.2 (VLT residência) | 40% | 19% | 13% | 85 | 154 | 24 / 107 | 159 / 181 | 36 | 0 |
| S3 `k_A`=5 (~7 s) | A2.1 (EDF) | 46% | 15% | 10% | 80 | 332 | 12 / 117 | 311 / 368 | 35 | 0 |
| S3 `k_A`=5 (~7 s) | A9.4 (VLT, preempção por troca, λ=1) | 40% | 23% | 18% | 87 | 165 | 30 / 115 | 174 / 198 | 37 | 6 |
| S6 `k_R`=1 (~16 s) | A0.2+A1 (ociosidade 10 s) | 67% | 6% | 2% | 67 | 477 | 5 / 188 | 447 / 520 | 0 | 0 |
| S6 `k_R`=1 (~16 s) | A0.4 (troca por throughput) | 50% | 21% | 15% | 86 | 172 | 18 / 79 | 152 / 210 | 51 | 0 |
| S6 `k_R`=1 (~16 s) | A9.2 (VLT residência) | 47% | 27% | 21% | 89 | 158 | 25 / 111 | 164 / 186 | 36 | 0 |
| S6 `k_R`=1 (~16 s) | A2.1 (EDF) | 52% | 22% | 15% | 82 | 297 | 14 / 117 | 267 / 363 | 36 | 0 |
| S6 `k_R`=1 (~16 s) | A9.4 (VLT, preempção por troca, λ=1) | 44% | 26% | 22% | 89 | 164 | 29 / 112 | 167 / 201 | 37 | 8 |
| S6 `k_R`=2 (~31 s) | A0.2+A1 (ociosidade 10 s) | 73% | 7% | 2% | 69 | 477 | 5 / 188 | 447 / 520 | 0 | 0 |
| S6 `k_R`=2 (~31 s) | A0.4 (troca por throughput) | 64% | 31% | 25% | 89 | 172 | 18 / 79 | 152 / 210 | 51 | 0 |
| S6 `k_R`=2 (~31 s) | A9.2 (VLT residência) | 55% | 33% | 28% | 91 | 170 | 28 / 116 | 175 / 197 | 34 | 1 |
| S6 `k_R`=2 (~31 s) | A2.1 (EDF) | 64% | 32% | 23% | 88 | 271 | 14 / 95 | 228 / 323 | 38 | 0 |
| S6 `k_R`=2 (~31 s) | A9.4 (VLT, preempção por troca, λ=1) | 57% | 36% | 30% | 93 | 152 | 22 / 101 | 157 / 183 | 37 | 8 |
| S6 `k_R`=4 (~63 s) | A0.2+A1 (ociosidade 10 s) | 78% | 11% | 5% | 73 | 477 | 5 / 188 | 447 / 520 | 0 | 0 |
| S6 `k_R`=4 (~63 s) | A0.4 (troca por throughput) | 84% | 54% | 43% | 95 | 172 | 18 / 79 | 152 / 210 | 51 | 0 |
| S6 `k_R`=4 (~63 s) | A9.2 (VLT residência) | 74% | 56% | 50% | 96 | 144 | 26 / 103 | 151 / 166 | 37 | 0 |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) | 80% | 56% | 49% | 96 | 194 | 16 / 88 | 172 / 242 | 38 | 0 |
| S6 `k_R`=4 (~63 s) | A9.4 (VLT, preempção por troca, λ=1) | 71% | 52% | 45% | 95 | 164 | 29 / 114 | 169 / 202 | 35 | 5 |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) com preempção | 79% | 62% | 55% | 97 | 215 | 24 / 110 | 248 / 371 | 58 | 357 |


### Tabela B1: braço − A0.4 (troca por throughput), pareado no job, no nível do braço (20 jobs)

| Nível | Braço | só TTFT (pts) | só TPOT 5×P95 (pts) | combinado (pts) | pior quarto (pts) | Jain ×100 | p90 pior modelo (s) | maior espera (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 (~7 s) | A9.2 (VLT residência) | -1,4 [-5,9; 3,4] | -1,4 [-5,5; 2,9] | -0,2 [-5,0; 5,1] | 5,2 [2,7; 7,5]\* | 5,4 [3,1; 7,5]\* | -18,2 [-42,9; 7,6] | -28,5 [-54,0; -1,7]\* |
| S3 `k_A`=5 (~7 s) | A2.1 (EDF) | 4,3 [0,8; 7,6]\* | -0,4 [-2,8; 2,0] | 3,5 [-0,3; 7,4] | 0,7 [-2,0; 3,4] | -0,3 [-2,7; 2,0] | 159,9 [118,4; 203,0]\* | 158,2 [121,7; 197,1]\* |
| S3 `k_A`=5 (~7 s) | A9.4 (VLT, preempção por troca, λ=1) | -1,7 [-6,3; 3,0] | -2,8 [-7,5; 1,6] | -1,8 [-7,4; 3,8] | 8,5 [4,7; 12,4]\* | 7,2 [3,0; 11,5]\* | -7,6 [-34,8; 20,3] | -11,4 [-42,3; 23,3] |
| S6 `k_R`=1 (~16 s) | A9.2 (VLT residência) | -2,9 [-9,0; 2,9] | -3,7 [-10,3; 2,3] | -1,8 [-9,1; 5,3] | 6,1 [2,0; 10,2]\* | 2,9 [0,6; 5,1]\* | -14,3 [-40,3; 11,8] | -23,5 [-53,7; 8,3] |
| S6 `k_R`=1 (~16 s) | A2.1 (EDF) | 2,3 [-3,1; 7,9] | -2,4 [-9,1; 4,0] | 1,4 [-5,6; 8,7] | 0,4 [-4,5; 5,4] | -3,7 [-6,9; -0,5]\* | 124,6 [98,1; 150,3]\* | 152,7 [115,9; 198,2]\* |
| S6 `k_R`=1 (~16 s) | A9.4 (VLT, preempção por troca, λ=1) | -6,4 [-11,2; -2,1]\* | -5,7 [-11,1; -0,8]\* | -6,0 [-11,9; -0,4]\* | 5,3 [0,0; 9,9]\* | 2,9 [-0,9; 6,1] | -8,5 [-37,4; 21,0] | -9,2 [-36,0; 19,2] |
| S6 `k_R`=2 (~31 s) | A9.2 (VLT residência) | -8,8 [-13,5; -4,5]\* | -5,3 [-11,6; 0,6] | -8,3 [-15,4; -1,6]\* | 1,7 [-3,6; 6,9] | 1,2 [-1,9; 4,4] | -2,1 [-31,3; 25,8] | -12,7 [-43,2; 16,7] |
| S6 `k_R`=2 (~31 s) | A2.1 (EDF) | -0,4 [-3,5; 2,7] | 1,5 [-2,0; 5,3] | 0,7 [-4,3; 5,6] | 0,4 [-4,2; 5,0] | -1,4 [-3,4; 0,4] | 98,4 [65,4; 135,0]\* | 113,4 [79,8; 148,6]\* |
| S6 `k_R`=2 (~31 s) | A9.4 (VLT, preempção por troca, λ=1) | -7,4 [-11,8; -3,0]\* | -0,8 [-4,2; 2,8] | -5,8 [-11,5; 0,3] | 4,7 [-0,1; 9,3] | 3,5 [1,5; 5,7]\* | -20,0 [-43,2; 1,7] | -26,6 [-47,7; -6,7]\* |
| S6 `k_R`=4 (~63 s) | A9.2 (VLT residência) | -9,7 [-13,3; -6,3]\* | -2,5 [-6,7; 1,7] | -7,4 [-12,2; -2,5]\* | 2,1 [-3,3; 7,1] | 1,4 [-0,4; 3,3] | -28,2 [-49,5; -7,6]\* | -44,0 [-62,6; -26,4]\* |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) | -3,6 [-7,5; 0,7] | 1,8 [-2,5; 6,3] | -1,4 [-8,1; 5,5] | 2,0 [-5,7; 9,7] | 1,2 [-0,4; 3,0] | 21,8 [-8,7; 51,2] | 32,4 [1,1; 62,5]\* |
| S6 `k_R`=4 (~63 s) | A9.4 (VLT, preempção por troca, λ=1) | -12,5 [-16,5; -8,6]\* | -4,5 [-9,1; 0,4] | -10,8 [-17,0; -4,0]\* | -1,9 [-8,5; 4,9] | 0,2 [-1,7; 2,1] | -7,8 [-23,9; 8,5] | -7,8 [-28,1; 13,2] |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) com preempção | -4,7 [-8,9; -0,6]\* | 3,4 [-1,6; 8,4] | -0,3 [-6,7; 6,4] | 8,4 [1,6; 15,4]\* | 2,3 [0,7; 4,2]\* | 43,0 [-2,6; 94,3] | 161,1 [112,8; 210,4]\* |


### Tabela B2: braço − A9.2 (VLT residência), pareado no job, no nível do braço (20 jobs)

| Nível | Braço | só TTFT (pts) | só TPOT 5×P95 (pts) | combinado (pts) | pior quarto (pts) | Jain ×100 | p90 pior modelo (s) | maior espera (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 (~7 s) | A2.1 (EDF) | 5,7 [2,2; 9,1]\* | 1,0 [-2,6; 4,8] | 3,7 [-0,3; 7,6] | -4,5 [-7,3; -1,4]\* | -5,7 [-7,7; -3,6]\* | 178,1 [136,6; 222,9]\* | 186,7 [145,3; 229,0]\* |
| S3 `k_A`=5 (~7 s) | A9.4 (VLT, preempção por troca, λ=1) | -0,3 [-3,9; 3,6] | -1,4 [-6,7; 4,4] | -1,6 [-5,5; 2,9] | 3,3 [-0,5; 7,4] | 1,8 [-1,8; 5,8] | 10,6 [-27,6; 49,0] | 17,1 [-26,5; 61,9] |
| S6 `k_R`=1 (~16 s) | A2.1 (EDF) | 5,2 [2,0; 8,5]\* | 1,2 [-4,6; 6,6] | 3,3 [-1,3; 7,5] | -5,8 [-10,6; -0,8]\* | -6,7 [-9,4; -3,5]\* | 138,9 [104,1; 172,0]\* | 176,2 [128,5; 226,0]\* |
| S6 `k_R`=1 (~16 s) | A9.4 (VLT, preempção por troca, λ=1) | -3,5 [-7,2; -0,1]\* | -2,0 [-5,8; 1,6] | -4,2 [-8,3; -0,5]\* | -0,8 [-5,2; 3,2] | -0,1 [-4,2; 3,7] | 5,8 [-16,0; 27,5] | 14,2 [-7,2; 36,1] |
| S6 `k_R`=2 (~31 s) | A2.1 (EDF) | 8,4 [5,9; 11,3]\* | 6,9 [2,6; 11,6]\* | 9,0 [5,3; 13,4]\* | -1,3 [-7,2; 4,2] | -2,7 [-6,0; 0,5] | 100,5 [55,6; 149,1]\* | 126,2 [86,2; 169,6]\* |
| S6 `k_R`=2 (~31 s) | A9.4 (VLT, preempção por troca, λ=1) | 1,4 [-2,2; 5,2] | 4,5 [-0,9; 10,6] | 2,5 [-2,7; 8,2] | 3,0 [-2,2; 8,0] | 2,3 [-0,3; 4,9] | -17,9 [-41,8; 6,8] | -13,9 [-37,3; 11,5] |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) | 6,1 [1,7; 11,2]\* | 4,3 [-0,1; 9,0] | 6,0 [0,2; 11,8]\* | -0,0 [-7,7; 7,4] | -0,2 [-1,8; 1,5] | 50,0 [24,7; 76,9]\* | 76,4 [47,7; 105,9]\* |
| S6 `k_R`=4 (~63 s) | A9.4 (VLT, preempção por troca, λ=1) | -2,9 [-7,0; 1,3] | -2,0 [-6,5; 2,7] | -3,5 [-9,0; 2,2] | -4,0 [-10,6; 2,5] | -1,2 [-2,5; 0,0] | 20,4 [-1,1; 41,1] | 36,2 [15,9; 55,8]\* |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) com preempção | 5,0 [-0,2; 10,2] | 5,8 [0,6; 11,5]\* | 7,1 [0,7; 13,6]\* | 6,3 [-0,3; 12,8] | 0,9 [-0,6; 2,4] | 71,2 [19,7; 127,3]\* | 205,1 [149,5; 262,8]\* |


### Tabela C: por carga (5 repetições), braço − A0.4: total só TTFT / pior quarto (pontos)

| Nível | Braço | C1 | T1 | C6 | T3 |
| --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 (~7 s) | A9.2 (VLT residência) | 16,4\* / 6,0 | -15,2\* / 5,6\* | -3,7 / 4,1\* | -3,1 / 4,9\* |
| S3 `k_A`=5 (~7 s) | A2.1 (EDF) | 14,8\* / 2,9 | -7,0 / 4,8 | 7,8\* / -2,8\* | 1,6 / -2,1 |
| S3 `k_A`=5 (~7 s) | A9.4 (VLT, preempção por troca, λ=1) | 16,8\* / 13,2\* | -12,4\* / 9,1\* | -8,4\* / 1,0 | -3,0 / 10,7\* |
| S6 `k_R`=1 (~16 s) | A9.2 (VLT residência) | 16,9\* / 8,8\* | -10,2\* / 7,0\* | -12,6\* / -0,7 | -5,8 / 9,4 |
| S6 `k_R`=1 (~16 s) | A2.1 (EDF) | 16,3\* / 4,6 | -5,2 / 6,6 | -0,8 / -10,0\* | -1,3 / 0,3 |
| S6 `k_R`=1 (~16 s) | A9.4 (VLT, preempção por troca, λ=1) | 14,2\* / 10,1 | -16,2\* / 7,0\* | -13,1\* / -2,7 | -10,5\* / 6,8 |
| S6 `k_R`=2 (~31 s) | A9.2 (VLT residência) | 7,0\* / 4,8 | -11,7\* / 4,1 | -20,2\* / -5,1 | -10,5 / 2,9 |
| S6 `k_R`=2 (~31 s) | A2.1 (EDF) | 8,5\* / 4,1 | -7,3\* / 6,6 | -0,8 / -10,6\* | -2,1 / 1,3 |
| S6 `k_R`=2 (~31 s) | A9.4 (VLT, preempção por troca, λ=1) | 9,5\* / 10,7\* | -16,3\* / 0,6 | -13,0\* / 1,3 | -9,9 / 6,0 |
| S6 `k_R`=4 (~63 s) | A9.2 (VLT residência) | -4,7 / -1,3 | -9,2\* / -0,4 | -20,5\* / 0,7 | -4,2 / 9,2 |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) | 2,9 / 7,3 | -4,3 / 5,5 | -7,6\* / -7,0 | -5,4 / 2,2 |
| S6 `k_R`=4 (~63 s) | A9.4 (VLT, preempção por troca, λ=1) | -6,8\* / -9,2\* | -7,1 / 4,2 | -29,2\* / -8,9\* | -7,1 / 6,3 |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) com preempção | 11,2\* / 24,2\* | -11,7\* / 2,7 | -9,7\* / 1,9 | -8,6 / 4,8 |


### Tabela D: decomposição das violações de TTFT (% das enviadas, média dos 20 jobs)

Inevitável = o prazo é menor que o custo de ativação (`Ĉ_at`) ou da troca mais rápida (`Ĉ_rot` com preempção); evitável só com decisão antes da chegada = o prazo cobre o custo mas não o custo + um ciclo do controlador; TPOT em troca = violações de TPOT com o decode sobreposto a uma ativação/desativação (`polyaxon/slo_metrics.py`).

| Nível | Política | no prazo | inevitável (ativação) | inevitável (troca) | evitável só antes da chegada | evitável | TPOT violado em troca |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S3 `k_A`=5 (~7 s) | A0.2+A1 (ociosidade 10 s) | 61% | 0,0% | 0,0% | 17,0% | 22,1% | 6,7% |
| S3 `k_A`=5 (~7 s) | A0.4 (troca por throughput) | 42% | 0,0% | 0,0% | 13,4% | 44,8% | 15,1% |
| S3 `k_A`=5 (~7 s) | A9.2 (VLT residência) | 40% | 0,0% | 0,0% | 13,5% | 46,1% | 15,9% |
| S3 `k_A`=5 (~7 s) | A2.1 (EDF) | 46% | 0,0% | 0,0% | 12,8% | 41,2% | 14,9% |
| S3 `k_A`=5 (~7 s) | A9.4 (VLT, preempção por troca, λ=1) | 40% | 0,0% | 0,0% | 15,2% | 44,8% | 17,6% |
| S6 `k_R`=1 (~16 s) | A0.2+A1 (ociosidade 10 s) | 67% | 0,0% | 0,0% | 0,0% | 33,4% | 6,7% |
| S6 `k_R`=1 (~16 s) | A0.4 (troca por throughput) | 50% | 0,0% | 0,0% | 0,0% | 49,8% | 15,1% |
| S6 `k_R`=1 (~16 s) | A9.2 (VLT residência) | 47% | 0,0% | 0,0% | 0,0% | 52,7% | 18,0% |
| S6 `k_R`=1 (~16 s) | A2.1 (EDF) | 52% | 0,0% | 0,0% | 0,0% | 47,5% | 17,0% |
| S6 `k_R`=1 (~16 s) | A9.4 (VLT, preempção por troca, λ=1) | 44% | 0,0% | 0,0% | 0,0% | 56,2% | 20,0% |
| S6 `k_R`=2 (~31 s) | A0.2+A1 (ociosidade 10 s) | 73% | 0,0% | 0,0% | 0,0% | 27,5% | 6,7% |
| S6 `k_R`=2 (~31 s) | A0.4 (troca por throughput) | 64% | 0,0% | 0,0% | 0,0% | 35,8% | 15,1% |
| S6 `k_R`=2 (~31 s) | A9.2 (VLT residência) | 55% | 0,0% | 0,0% | 0,0% | 44,7% | 19,6% |
| S6 `k_R`=2 (~31 s) | A2.1 (EDF) | 64% | 0,0% | 0,0% | 0,0% | 36,3% | 13,3% |
| S6 `k_R`=2 (~31 s) | A9.4 (VLT, preempção por troca, λ=1) | 57% | 0,0% | 0,0% | 0,0% | 43,3% | 15,2% |
| S6 `k_R`=4 (~63 s) | A0.2+A1 (ociosidade 10 s) | 78% | 0,0% | 0,0% | 0,0% | 21,8% | 6,7% |
| S6 `k_R`=4 (~63 s) | A0.4 (troca por throughput) | 84% | 0,0% | 0,0% | 0,0% | 16,4% | 15,1% |
| S6 `k_R`=4 (~63 s) | A9.2 (VLT residência) | 74% | 0,0% | 0,0% | 0,0% | 26,1% | 17,5% |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) | 80% | 0,0% | 0,0% | 0,0% | 20,0% | 12,8% |
| S6 `k_R`=4 (~63 s) | A9.4 (VLT, preempção por troca, λ=1) | 71% | 0,0% | 0,0% | 0,0% | 29,0% | 19,5% |
| S6 `k_R`=4 (~63 s) | A2.1 (EDF) com preempção | 79% | 0,0% | 0,0% | 0,0% | 21,1% | 11,3% |


### Hipóteses

- **H1 confirmada.** No S3 `k_A`=5 a A9.2 tem pior quarto +5,2\* e Jain +5,4\* contra a A0.4 (triagem: +5,5 e +5,3).
  - O total não muda significativamente (−1,4). A maior espera cai 28 s\*.
  - O ganho de justiça é positivo nas 4 cargas (significativo em 3).
  - O mesmo vale no S6 `k_R`=1 (pior quarto +6,1\*, Jain +2,9\*, total −2,9 n.s.).
  - Custo: a requisição típica espera mais (TTFT p50 24 × 18 s, p90 107 × 79 s).
- **H2 refutada.** A A9.4 com λ = 1 preempta mais (5–8 requisições e 8–14 retrações por job; total de 103–154
  requisições em 20 jobs por nível), mas não é significativamente melhor que a A9.2 em nada:
  - no S3 `k_A`=5, pior quarto +3,3 n.s.;
  - no S6 `k_R`=1 perde total (−3,5\*);
  - no S6 `k_R`=4 piora a maior espera (+36 s\*).
- **H3 confirmada.** Com prazo de ≥ 2 trocas, nenhuma variante do VLT ganha da A0.4 em pior quarto (diferenças n.s.).
  - A A9.2 perde 9–10 pontos de total (−8,8\*, −9,7\*); a A9.4, 7–13.
  - A A0.4 tem o maior total no S6 `k_R`=4 (84%).
- **H4 em parte.** A A2.1 com preempção no S6 `k_R`=4 é a mais justa da campanha (pior quarto 62%: +8,4\* contra a A0.4,
  +6,3 n.s. contra a A9.2), mas:
  - perde total contra a A0.4 (−4,7\*);
  - tem a maior espera mais longa entre as políticas por prazo (371 s; +161 s\* contra a A0.4);
  - preempta ~357 requisições por job;
  - o ganho vem quase todo do C1 (+24 pontos de pior quarto); nas outras três cargas perde 9–12 pontos de total.
- **A2.1 sem preempção:** mais total que a A9.2 em todos os prazos (+5 a +8\*) e mais que a A0.4 no S3 `k_A`=5 (+4,3\*),
  com justiça igual à da A0.4. Porém tem cauda de ~2× (abaixo) e por isso falha o critério de maior espera (D52).

### O total depende da carga (tabela C)

O sinal da diferença de total da A9.2 contra a A0.4 muda com a carga. Por exemplo, no S3 `k_A`=5: C1 +16,4\*,
T1 −15,2\*.

Mecanismo, pelos logs de decisão (rotações e TTFT por carga, `analise/tabela_politicas.csv`):
- **C1 (10 modelos 8B iguais, carga constante):** as pontuações de throughput/GB dos modelos quase empatam, e a A0.4
  troca por diferenças pequenas: 31 rotações por job, contra 19 da A9.2. Cada troca custa ~16 s sem servir, e a A9.2,
  que só troca quando o atraso de quem entra supera o das vítimas, perde menos tempo trocando.
- **T1 (popularidade concentrada):** as duas rotacionam o mesmo (49 × 50), mas a A0.4 mantém os populares residentes
  (TTFT p50 4,8 s × 14,9 s) e assim cumpre mais requisições. A A9.2 gira para os modelos atrasados, que têm menos
  requisições.

## Diferenças maiores que 2×, explicadas

1. **A0.2+A1: a cauda é 2,5–3× a da A0.4 e das variantes do VLT.** O p90 do pior modelo é 477 s e a maior espera 520 s; o pior quarto fica em
   5–11%.
   - Mecanismo: o modelo só sai depois de 10 s sem requisições. Sob carga contínua, os populares residentes nunca ficam
     ociosos, e os modelos frios esperam a carga cair.
   - O outro lado: os populares ficam residentes, por isso o TTFT p50 de 5 s (3–6× menor) e o maior total nos prazos
     curtos.
   - Ela não troca por rotação (0 rotações): só despeja ociosos.
2. **A2.1 (EDF): cauda ~2× a da A0.4 e da A9.2.** No S3 `k_A`=5, o p90 do pior modelo é 332 × 172/154 s e a maior
   espera 368 × 210/181 s.
   - Mecanismo (`policy/deadline.py`, `edf_select`): o EDF ordena os modelos pelo prazo viável mais cedo. Quando todas
     as requisições de um modelo já passaram do prazo, elas contam como "perdidas" e o modelo vai para o fim da fila,
     por desenho (não favorecer filas perdidas). Um modelo que fica para trás continua para trás até a carga cair.
   - É maior no C6 (+293 s), em que a popularidade muda e um modelo que deixa de ser popular fica com fila perdida.
3. **A2.1 com preempção: maior espera 371 s e ~357 requisições preemptadas por job (0 sem preempção), 58 rotações × 38.**
   As requisições interrompidas recomeçam e voltam à fila, onde muitas viram "perdidas" (item 2).
4. **A9.2 e A9.4: TTFT p50 ~2× o do EDF** (22–30 × 12–16 s). As duas giram para os modelos que esperaram mais, então as
   requisições dos populares esperam mais. É o preço do pior quarto melhor.
5. **TPOT violado durante troca: 11–20% nas políticas que trocam × 6,7% na A0.2+A1** (tabela D). Ela não faz rotações.
   Nas outras, o decode de quem está residente divide a GPU e a CPU com a carga e a descarga de outro modelo.
6. **Preempções em braços sem preempção** (A9.2: média 1,2 no S6 `k_R`=2 e 0,3 no S6 `k_R`=4): vêm de 2 dos 80 níveis
   da A9.2 (`f615-c6n14-2` S6 `k_R`=2: 24 requisições; `f615-t3-4` S6 `k_R`=4: 6). Nos dois, o controlador acionou a
   quebra de impasse (`evict_deadlock`, A1, 30 s), que despeja um modelo ocupado para que outro caiba. É um mecanismo de
   segurança, não a política.

## Decomposição das violações (tabela D)

- **Nenhuma violação de TTFT é inevitável em nenhum braço** (0,0%). Isso decorre dos níveis: todo prazo é ≥ a troca mais
  rápida (`Ĉ_rot` com preempção, ~6,4 s num 8B) e ≥ o custo de ativação.
- **No S3 `k_A`=5, 13–17% das enviadas só seriam cumpridas com uma decisão antes da chegada:** o prazo cobre o custo,
  mas não o custo mais um ciclo do controlador (5 s). É a parte que só prever a chegada resolveria; a A2.3 tentou e
  piorou a justiça (F6.16).
- O resto das violações é evitável. Nos prazos de troca, elas são a fila: há mais demanda do que trocas cabem no tempo.

## Anomalias e investigações

1. **Download truncado de `f615-c1n10-1`:** a primeira transferência veio incompleta. O job foi baixado de novo à mão,
   com o driver parado, e o pod uuid foi conferido. Correção: `442c8a3` (o driver limpa o destino antes de cada
   tentativa). Depois disso, nenhuma falha.
2. **Código da campanha × D59 (`8912fbf`, 2026-11-11 11:23):** a D59 mudou o ciclo de vida (comandos com `rid`), e
   `submit.sh` envia o `python/` da árvore no momento da submissão. Os jobs não guardam hash do código. Verificação pelos
   logs:
   - nenhum dos 20 jobs tem mensagens que só existem no código novo ("Ignoring a late …", "got no answer for",
     "late … answer");
   - 18 dos 20, inclusive a última submissão (`f615-t3-5`, 08:00 UTC), têm a mensagem que só existe no código antigo
     ("Ignoring the late deactivation of");
   - logo, todos rodaram o código anterior à D59, como a própria D59 registra.
   - **Limitação:** o defeito 1 da D59 (um "activated" atrasado de uma carga despejada confirmava uma ativação nova)
     estava presente em todos os braços. As comparações pareadas são dentro do mesmo código, mas os valores absolutos
     podem mudar com a D59. A linha de base da F14 roda A0.4, A9.2 e A2.1 de novo, com o código novo (regra 3).
3. Nenhum nível inválido, nenhum K1, nenhuma reexecução.

## Critérios de aceitação (F6, `PLANO_AGENTE.md`)

| Critério | Situação | Evidência |
| --- | --- | --- |
| Testes passando | **OK:** 193 testes unitários + `test_memory_robustness.py` (8 pulados), no HEAD (inclui a D59) | `tests/`, `test/multi-model/` |
| Linhas de base no mesmo job | **OK:** A0.2+A1 e A0.4 em todos os 20 jobs | suítes `f615_*_suite.tsv` |
| Por carga, diferença contra cada linha de base com IC 95% pareado, nas três vistas | **OK:** só TTFT, só TPOT 5×P95, combinado; 20 jobs e por carga (5 rep.) | `analise/pareado.csv`, `tabelas.md` (B1–B3, C) |
| Decomposição das violações | **OK:** inevitável × evitável por braço no seu nível (é a F6.18 feita sobre estes dados) | `analise/decomposicao.csv`, tabela D |
| Métricas de justiça | **OK:** pior quarto, pior modelo, Jain, p90 do pior modelo, maior espera | `analise/justica*.csv`, tabela A |
| Toda diferença > 2× explicada pelos logs de decisão | **OK:** 6 casos acima | eventos `events.csv` e decisões por nível |

## Leitura contra o objetivo (D52)

Não há uma vencedora única:
- **Prazo curto (≤ 1 troca):**
  - a **A9.2** é a única que melhora a justiça com significância sem perda significativa de total (pior quarto +5 a +6,
    Jain +3 a +5, maior espera −28 s\* no S3 `k_A`=5);
  - a A9.4 não se distingue dela;
  - a A2.1 ganha total, mas falha na maior espera.
- **Prazo de ≥ 2 trocas:** a **A0.4** é tão justa quanto as outras e tem 7–13 pontos a mais de total que as variantes
  do VLT. Ela empata em total com a A2.1, que tem cauda pior. Lá a A0.4 é a melhor política.
- A **A0.2+A1** maximiza o total deixando 2–5 modelos com fome (pior quarto 5–11%) e continua inaceitável sob a D52.

Pela seção 7, uma política que melhora a justiça com custo de total cuja significância depende do limiar de "grande
perda" (A9.2 nos prazos de ≥ 2 trocas: −9 a −10 pontos) fica a critério do Gabriel. Esse limiar está pendente para o
início da F14 (`PLANO_AGENTE.md` seção 8, item 2).

## Decisões para o gate da F6 (Gabriel)

1. **Aprovar o gate da F6.** Todos os critérios estão OK, com a decomposição desta campanha valendo como F6.18.
2. **Qual é a "vencedora da F6.15".** O nome entra na linha de base da F14 (F14.5), nas adaptações A14 e nas comparações
   da F13 e da F15. Proposta do agente: **A9.2**, por ser a única com ganho de justiça confirmado no prazo curto, sem
   preempção (mais simples) e com a menor maior espera em 3 dos 4 prazos. A A9.4 não acrescenta nada e sai. Como a lista da F14 já tem
   A0.2+A1, A0.4, A9.2 e A2.1, escolher a A9.2 não acrescenta braço.
3. **F6.17 (sensibilidade só da vencedora).** As opções:
   - (a) fazer reduzida: margem e α da A9.2, 2 repetições, C1 e T1 (as cargas em que o total vai em sentidos opostos),
     S3 `k_A`=5 e S6 `k_R`=1; uma onda de ~4 jobs, ~4,5 h;
   - (b) pular, porque a F14 adapta a A9.2 ao tamanho dos modelos e os parâmetros afinados com 8B iguais podem não
     valer lá.
   O agente sugere (a), porque o ganho da A9.2 é pequeno (+5 pontos) e o custo é uma onda.
4. **F6.9 (relatório da F6)** em seguida, juntando F6a, F6.0, F6.16 e esta confirmação, inclusive os resultados
   negativos (A9.4, A2.3, A3.1, A10.1 e a preempção global).

## Pendências

- Gate da F6 (acima), F6.17 conforme a decisão, F6.9.
- Limiar de "grande perda de SLO" (início da F14).
- Recalcular a A9.2 e a A0.4 com o código da D59 na linha de base da F14 (limitação do item 2 das anomalias).

## Reprodução

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
bash polyaxon/f6_15_suites.sh                      # suítes polyaxon/configs/f615_*_suite.tsv e f615_queue.tsv
bash polyaxon/f4_driver_start.sh f615              # até 3 jobs; estado reports/data/F06/f615/jobs.tsv
# (o driver baixa um job de cada vez, confere o pod uuid e roda o validador; à mão:)
/mnt/scratch/scheduler/polyax-env/bin/polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs \
  --path /mnt/scratch/scheduler/prism-raw/F6/f615/<job>
python3 polyaxon/validate_run.py --csv reports/data/F06/f615/validador/<job>.csv /mnt/scratch/scheduler/prism-raw/F6/f615/<job>
# análise
$PY polyaxon/f60_analysis.py reports/data/F06/f615/analise reports/data/F06/f615/validador/f615-*.csv
$PY polyaxon/f60_fairness.py reports/data/F06/f615/analise
$PY polyaxon/f615_compare.py reports/data/F06/f615/analise > reports/data/F06/f615/analise/f615_compare.txt
$PY polyaxon/f615_decomp.py reports/data/F06/f615/analise > reports/data/F06/f615/analise/decomposicao.txt
$PY polyaxon/f615_report_tables.py reports/data/F06/f615/analise     # tabelas.md
```

Bases dos SLOs: `reports/registro/latencia_ref.md` (S3, S6, S1D), `reports/registro/c_rot.json`,
`reports/registro/latencia_ded.json`.
