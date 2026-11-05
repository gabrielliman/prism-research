# F06a — Primeira rodada das políticas por prazo (A2.1 EDF e A9.1 LVF): triagem

Data de início / fim: 2026-11-04 / 2026-11-05 (triagem F6a.1–F6a.6; confirmação F6a.8 não executada, D27)
Commits: nenhum (o Gabriel commita). Código das execuções: `e04db5e` + diff. O trabalho está no worktree `.claude/worktrees/f6a` (branch `f6a-deadline`). O diff da versão v2 está em `reports/data/F06a/codigo/v2_e04db5e.diff`; a v1 é a v2 sem as duas correções da D26.

## Objetivo

Responder cedo à pergunta central da F6 (D24): escolher quem entra na GPU pela **folga** (A2.1, EDF entre modelos) ou pelo **atraso acumulado** (A9.1, Virtual Lag Time do SuperInfer) melhora o SLO em relação às linhas de base, nas cargas atuais com disputa por residência (C1, T1)?

## Hipóteses

- H1. Com prazos curtos (S2 `k_T` = 10 e 25: 0,64–1,75 s, abaixo de `Ĉ_at` + um ciclo), quase nenhuma requisição de modelo inativo é viável (observação 4.0). A A2.1 então quase não tem folga para usar, e se comporta como um despejo de ociosos.
- H2. Com prazo folgado (S3 `k_A` = 5: 7,0 s), a A2.1 consegue salvar requisições de modelos inativos e deve ganhar das linhas de base.
- H3. A A9.1 reduz o pior atraso (pior modelo, fome), possivelmente à custa do total, porque escolhe a vítima só pelo tempo de residência (risco (ii) da seção A9).
- H4. O ciclo de 1 s ajuda as duas políticas, porque o ciclo de 5 s é maior que a folga.

## Mudanças de código

| Arquivo | O que muda | Variável / padrão |
| --- | --- | --- |
| `python/sglang/multi_model/scheduling/policy/deadline.py` (novo) | funções puras `edf_select` (A2.1) e `lvf_select` (A9.1): retrato → (ativações, vítimas, pontuação por modelo) | — |
| `policy/simple_global.py` | `_deadline_snapshot` monta o retrato; com `edf`/`lvf`, `_deadline_actions` substitui os passos 3/3b. Também: reserva mínima de KV (A1.1) e residência mínima (A1.3) | `PRISM_EVICTION=edf\|lvf` (padrão `idle`, inalterado); `PRISM_EDF_FLOOR` (0), `PRISM_EDF_BUDGET` (1), `PRISM_LVF_ALPHA` (3), `PRISM_LVF_BETA_F` (0,5), `PRISM_LVF_BETA_B` (0), `PRISM_LVF_BUDGET` (1), `PRISM_KV_RESERVE_REQS` (0 = desligado), `PRISM_MIN_RESIDENCY` (0 = desligado), `PRISM_CAT_A/B/C`, `PRISM_PREFILL_A/B` |
| `scheduling/decision_log.py` | campo `policy` por ciclo: nome, pontuação de cada modelo (folga `u`, viáveis/perdidas; ou `vlt`), rotações em andamento, modelos para os quais houve rotação (F6a.4) | só com `PRISM_DECISION_LOG` |
| `polyaxon/overload_load.py` | `--slo-spec FAM:k=v` com `--slo-config`/`--slo-scenario`: SLO por requisição com a regra e as bases do `slo_metrics.py`; o prazo de TTFT vai ao servidor (F6a.1) | `PRISM_OVL_SLO_SPEC` no `run_examples.sh`; sem ele, nada muda (atingimento continua por `--slo-ttft/--slo-tpot`) |
| `polyaxon/slo_metrics.py` | `bases_for()`, usada pelas métricas e pelo gerador (mesma base nos dois) | — |
| `polyaxon/submit.sh` | envia `slo_metrics.py`, `latencia_ded.json`, `latencia_ref.json`, `cat_model.json` | — |
| `polyaxon/extract_ovl.py`, `ovl_plots.py` | eventos `evict_edf`, `evict_lvf`; coluna "rodízios por prazo" | — |
| `python/sglang/srt/managers/scheduler.py` | **P13** (D26): na última etapa de uma desativação sem preempção, requisições retraídas que não podem rodar voltam ao Redis em vez de travar a desativação | `PRISM_DEACTIVATE_EVICT_STUCK` (1; 0 = antigo) |
| `polyaxon/f6a_triage.py` (novo) | análise da triagem: só VALIDA, diferença pareada no mesmo job, três vistas | — |

Testes (F6a.3, seção 0.6): `tests/policy/test_deadline.py` (28 testes: tudo cabe, fome C1, troca de grupo C2, impasse C3, fila inviável, rotativo com `α`, orçamento, `T_min`, memória no limite, reserva, cooldown, vítima bloqueada, ligação com `SimpleGlobalPolicy`, A1.1, padrão inalterado) e `tests/robustness/test_deactivate_evict_stuck.py` (P13). Os 45 testes de `tests/policy`, `tests/controller` e `tests/robustness` passam.

Desenho e parâmetros: `decisoes.md` D25 (desenho, parâmetros) e D26 (correções no meio da triagem). Observação nova: `observacoes.md` O3 (as linhas de base usam o SLO enviado na ordem de ativação; por isso rodam com S1).

## Configurações executadas

**Relevância das cargas (seção 0.9):** C1 `ovl_mem` 0,2 (fome sem ociosidade, 10 × 8B, 6 ativos) e T1 `ovl_trace_big` ts1 (trace real, 12 × 8B, popularidade desigual) têm disputa por residência. C3 fica para a F4 (impasse), C4/C5 não têm ativações, C2 entra só na confirmação (D24).

**Parâmetros comuns das políticas novas (D25):** vítimas drenadas sem preempção (P0D1, como a A0.3), folga de ativação de 3 GB (como A0.3 e `fair`), `T_min` = 10 s, A1.1 desligada, ciclo de 5 s salvo nas linhas "1 s". O `k_D` só entra nas métricas (= 5).

| Suíte (`polyaxon/configs/`, gitignored) | Conteúdo | Jobs |
| --- | --- | --- |
| `f6a_smoke_suite.tsv` | EDF e LVF, C1, S3 `k_A`=5 | `d8eed798` |
| `f6a_tri_c1_suite.tsv`, `f6a_tri_t1_suite.tsv` | A0.1, A0.2, A0.3, `fair` (S1 enviado) intercaladas com EDF e LVF em S2 `k_T`=10, S2 `k_T`=25, S3 `k_A`=5 | C1: `4dd777d1`, `1390b57c`; T1: `1460d2fb` (código v1), `21f31370` (v2) |
| `f6a_tri_c1_edf2_suite.tsv`, `f6a_tri_t1_edf2_suite.tsv` | EDF v2 (3 níveis) pareada com A0.1 e A0.2 | C1: `940e60ed`, `f9c41c00`; T1: `4e87d5f8` |
| `f6a_cyc1_c1_suite.tsv`, `f6a_cyc1_t1_suite.tsv` | ciclo de 1 s no melhor nível de cada política (C1: EDF S2 `k_T`=25, LVF S3; T1: EDF S2 `k_T`=10, LVF S3), com A0.1 e A0.2 | C1: `1507c2a3`, `2a7a12ad`; T1: `9c9bc873`, `dc046edf` |

Desvio da matriz da D24 (48 níveis): **74 níveis**. Motivos: refazer a EDF depois da correção da D26 (+15), a T1 r2 parada e refeita (`2376c727`, sem dados), A0.1/A0.2 dentro dos jobs de ciclo 1 s para parear (+8), e o smoke (2).

## Execuções

| Job | Níveis | Validador | Observação |
| --- | --- | --- | --- |
| `d8eed798` smoke | 2 | 2 VALIDA | 15 rotações EDF, 16 LVF; F6a.5 OK |
| `4dd777d1` tri-c1-1 | 10 | 10 VALIDA | EDF v1 |
| `1390b57c` tri-c1-2 | 10 | 9 VALIDA, 1 INVALIDA_SISTEMA | `edf_S3k5`: V3 (desativação de 344 s, ativação de 253 s) → P13, abaixo |
| `1460d2fb` tri-t1-1 | 10 | 10 VALIDA | EDF v1 |
| `2376c727` tri-t1-2 | — | parado | EDF v1 com o desvio da D26; parado ao iniciar |
| `21f31370` tri-t1-2b | 10 | 10 VALIDA | código v2 |
| `940e60ed`, `f9c41c00` edf2-c1 | 5 + 5 | 10 VALIDA | reexecução da configuração da P13 (`edf_S3k5` C1) com a correção: VALIDA nas duas |
| `4e87d5f8` edf2-t1-1 | 5 | 5 VALIDA | completa a T1 r1 com EDF v2 |
| `1507c2a3`, `2a7a12ad` cyc1-c1 | 4 + 4 | 8 VALIDA | |
| `9c9bc873`, `dc046edf` cyc1-t1 | 4 + 4 | 8 VALIDA | |

Validador: `reports/data/F06a/validador/*.csv`. Dados brutos: `/mnt/scratch/scheduler/prism-raw/F6a/smoke`, `/mnt/scratch/scheduler/prism-raw/F6a-tri/<job>`. Nenhuma requisição perdida (todos os níveis com `unserved = failed = 0`).

## Resultados

Tabela completa (por repetição): `reports/data/F06a/triagem/resumo.md`; níveis: `niveis.csv`; pares: `pareado.csv`. Bases do S2/S3: `reports/registro/latencia_ref.md` (S2 = P95 da carga em GPU dedicada, D20/D21). **Comparação sempre pareada dentro do mesmo job** contra a melhor de A0.1 e A0.2, porque o A0.1 variou de 48 % a 75 % (S1) entre jobs do T1 com o mesmo código (ver "Anomalias").

### Diferença pareada (pontos percentuais, média de 2 repetições; política no próprio nível de SLO; EDF = v2)

| Carga | Política | SLO | Combinado | Só TTFT | Só TPOT | Pior modelo | Rotações/min |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | EDF | S2 `k_T`=10 | −26,5 | −28,9 | −7,3 | +7,8 | 0,75 |
| C1 | EDF | S2 `k_T`=25 | −18,1 | −23,7 | +2,0 | +9,1 | 1,96 |
| C1 | EDF | S3 `k_A`=5 | −27,2 | −33,5 | +1,8 | +13,0 | 2,61 |
| C1 | LVF | S2 `k_T`=10 | −34,1 | −34,1 | −5,6 | +12,9 | 2,63 |
| C1 | LVF | S2 `k_T`=25 | −36,9 | −36,6 | −5,2 | +18,7 | 2,63 |
| C1 | LVF | S3 `k_A`=5 | −32,1 | −31,3 | −4,9 | +9,3 | 2,97 |
| C1 | EDF, ciclo 1 s | S2 `k_T`=25 | −31,7 | −26,1 | −11,4 | 0,0 | 1,24 |
| C1 | LVF, ciclo 1 s | S3 `k_A`=5 | −39,1 | −39,1 | −0,3 | +15,8 | 9,68 |
| T1 | EDF | S2 `k_T`=10 | **−1,3** (−3,2; +0,6) | −1,4 | −0,3 | **+8,6** | 3,05 |
| T1 | EDF | S2 `k_T`=25 | **−2,9** (−4,3; −1,4) | −4,8 | 0,0 | **+20,5** (+32,0; +9,1) | 3,13 |
| T1 | EDF | S3 `k_A`=5 | −30,9 | −32,5 | −4,1 | +13,6 | 4,79 |
| T1 | LVF | S2 `k_T`=10 | −24,9 | −26,2 | −1,1 | +22,5 | 3,28 |
| T1 | LVF | S2 `k_T`=25 | −25,5 | −28,4 | +0,3 | +29,2 | 4,02 |
| T1 | LVF | S3 `k_A`=5 | −26,0 | −28,2 | −1,6 | +16,2 | 3,64 |
| T1 | EDF, ciclo 1 s | S2 `k_T`=10 | −8,6 (−21,2; +4,0) | −5,5 | −4,4 | +15,0 | 2,77 |
| T1 | LVF, ciclo 1 s | S3 `k_A`=5 | −35,5 | −43,7 | +1,7 | +11,9 | 8,81 |

As linhas de base que rodam (A0.3, `fair`) ficaram, nos jobs da etapa 1, em 19–31 % (C1) e 44–64 % (T1) no combinado, contra 66–69 % e 75–81 % da A0.1/A0.2 (`resumo.md`, última tabela). Na mesma comparação, EDF e LVF ficam **acima** da A0.3 e no nível do `fair`.

### Decomposição das violações e evitáveis × inevitáveis (média dos jobs; %; `slo_metrics.py`)

| Carga, SLO | Config | Atende ambos | Viola só TTFT | Viola só TPOT | Viola ambos | TTFT inevitável | TTFT evitável |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1, S2 `k_T`=10 | A0.1 | 58,9 | 37,9 | 2,7 | 0,5 | 34,1 | 4,3 |
| C1, S2 `k_T`=10 | EDF | 25,4 | 64,5 | 3,0 | 7,1 | 31,0 | 40,7 |
| C1, S2 `k_T`=10 | LVF | 32,5 | 61,9 | 0,0 | 5,6 | 32,0 | 35,6 |
| T1, S2 `k_T`=10 | A0.1 | 71,0 | 24,2 | 2,8 | 2,1 | 18,1 | 8,1 |
| T1, S2 `k_T`=10 | EDF | 66,9 | 27,3 | 2,8 | 2,9 | 20,0 | 10,2 |
| T1, S2 `k_T`=10 | LVF | 46,9 | 47,8 | 1,7 | 3,6 | 33,2 | 18,2 |
| T1, S3 `k_A`=5 | A0.1 | 76,0 | 19,1 | 4,8 | 0,1 | 0,0 | 19,2 |
| T1, S3 `k_A`=5 | EDF | 45,0 | 45,5 | 5,5 | 4,0 | 0,0 | 49,5 |

Com S2 `k_T`=10 no C1, 34 dos 38 pontos de violação da A0.1 são inevitáveis (chegaram a um modelo inativo com prazo < `Ĉ_at`). As políticas novas não reduzem essa parte e **criam** violações evitáveis (+36 a +40 pontos): o prejuízo vem das rotações. Com S2/S3 de `k_T`/`k_A` maiores, nenhuma violação é inevitável pela definição (prazo ≥ `Ĉ_at`), e a perda é toda evitável.

### Mecanismos, pelos logs de decisão (`decisions.jsonl`, campo `policy`)

- **EDF com S2 (prazo 0,64–1,75 s): H1 confirmada.** No T1, das 33–36 rotações por repetição, 0–4 foram para uma requisição viável; as vítimas foram quase todas modelos sem nada na fila; a média de modelos inativos com requisição viável por ciclo foi 0,0–0,04. A EDF vira um despejo de ociosos com `T_min` e reserva, e por isso empata com a A0.1/A0.2 no T1 (−1,3 e −2,9 pontos) e melhora o pior modelo (+8,6 e +20,5). No C1 não há modelo ocioso: as rotações para filas perdidas não têm vítima, e as poucas que acontecem custam (−18 a −27).
- **EDF com S3 (7 s): H2 refutada.** Há 2,3–2,4 modelos inativos com requisição viável por ciclo, e 34–38 das 36–41 rotações são para elas; 39 vítimas por repetição estavam ocupadas. A A2.1 decide pela folga de quem entra e não pesa o que a vítima perde (a fila dela, interrompida e drenada): −31 pontos no T1, −27 no C1. Essa é exatamente a parte que a A3 (despejo por perda esperada) deveria resolver.
- **LVF: H3 confirmada.** As vítimas são escolhidas pelo tempo de residência: 70–75 % ocupadas no T1 (2–5 requisições na fila), quase todas no C1 (5–8). Melhora o pior modelo (+9 a +29) e perde 25–37 pontos no combinado.
- **Ciclo de 1 s: H4 refutada.** Piora as duas: a LVF passa de ~3 para ~9–10 rotações por minuto, quase todas de modelos ocupados (78 de 88 no T1, 53 de 54 no C1); a EDF no T1 varia de −21 a +4 entre as repetições.
- **TPOT:** as perdas estão quase todas no TTFT; a vista só TPOT varia de −11 a +3 pontos (mais rotação, mais TPOT violado no C1 a 1 s).

## Anomalias e investigações

1. **P13 — desativação travada (job `1390b57c`, `edf_S3k5` C1 r2, V3).**
   - **Linha do tempo:** o worker do `model_3` drenou 15 s (15:41:21–15:41:37), devolveu 13 requisições ao Redis e ficou com 1 para terminar; um *decode out of memory* retraiu essa requisição para a fila de espera; `_run_to_completion_normal()` sem prazo ficou girando sem nada para rodar (o KV livre tinha ido para outras ativações). O controlador reativou o `model_3` por cima (15:42:27), e a ativação do `model_9` que caiu no mesmo worker nunca terminou.
   - **Classificação:** falha nova do sistema (`reports/erros.md`, P13). Mesmo caminho da A0.3 (P0D1), do `fair` e dos despejos por ociosidade, mas só dispara quando a requisição retraída não volta a caber.
   - **Correção e verificação:** `scheduler.py` (`evict_stuck`), teste `tests/robustness/test_deactivate_evict_stuck.py`; a configuração original rodou de novo com a correção nos jobs `940e60ed` e `f9c41c00`: VALIDA nas duas. O aviso `P13:` não apareceu em nenhum dos 73 níveis válidos. Evidência: `reports/data/F06a/inv_P13/`.
2. **Desvio da A2.1 em relação à D25** (achado na mesma investigação): a memória liberada por uma rotação podia voltar para a própria vítima (o `model_5` esperou ~300 s). Corrigido (`deadline.py`, teste `test_reserved_lost_model_beats_viable_victim`); os níveis EDF da etapa 1 ficam como "v1", só como diagnóstico (D26). A diferença v1 × v2 não muda as conclusões no C1 nem no T1 com S2; no T1 com S3 a v1 perdeu menos (−6,7 em 1 repetição) que a v2 (−31): a v1 rodou menos (2,75 contra 4,79 rotações/min), porque parte das rotações devolvia a memória à própria vítima; com uma repetição só, isso não foi investigado além disso.
3. **Deriva do nó nas linhas de base.** O A0.1 (mesmo caminho de código em todos os jobs, já que a P13 não disparou) ficou em S1:
   - C1: 65,9 / 65,9 % (etapa 1), 50,9 / 52,1 % (jobs EDF v2), 62,1 / 61,8 % (ciclo 1 s); outubro: ~64 %;
   - T1: 75,3 % (`t1-1`), 66,2 % (`t1-2b`), 70,8 % (`edf2-t1-1`), 73,8 / 48,5 % (ciclo 1 s); outubro: 78–80 %.

   Por isso toda comparação desta fase é pareada no mesmo job.

## Critérios de aceitação

| Critério (F6a) | Situação | Evidência |
| --- | --- | --- |
| Testes unitários passando | OK | 45 testes (`tests/policy`, `tests/controller`, `tests/robustness`) |
| Smoke e níveis da triagem válidos pelo validador | OK | 73 de 74 VALIDA; o inválido foi investigado (P13), corrigido e a configuração reexecutada com sucesso |
| Três vistas, decomposição, evitável × inevitável | OK | `reports/data/F06a/triagem/{resumo.md,niveis.csv}`, tabelas acima |
| Toda diferença grande explicada pelos logs de decisão | OK | seção "Mecanismos" |
| Regressão: A0.1 da triagem dentro da deriva de 28/10 e da F1 (~8 pontos) | **FALHOU em parte** | dentro em C1 etapa 1 (65,9 %), T1 `t1-1` (75,3 %) e ciclo 1 s do C1; fora em `t1-2b` (−12), nos jobs EDF v2 do C1 (−13) e em um job de ciclo 1 s do T1 (−30). O código do A0.1 é o mesmo em todos os jobs (as políticas novas só rodam com `edf`/`lvf`; a P13 não disparou), então é deriva do nó; a comparação pareada não é afetada. Fica para o Gabriel decidir se aceita |
| IC 95 % pareado na confirmação | N/A | só na F6a.8 |

**Sinal na triagem (D24: > ~8 pontos sobre a melhor linha de base do mesmo período):** **nenhuma configuração passou.** O melhor resultado é a EDF v2 com S2 no T1, que **empata** com a melhor linha de base no combinado (−1,3 e −2,9) e **melhora o pior modelo** (+8,6 e +20,5), nas duas repetições.

## Decisão do gate: APROVADO (Gabriel, 2026-11-05): opção 1, F6a fechada com resultado negativo, sem confirmação (D27)

O Gabriel seguiu a recomendação do agente: nenhuma configuração atingiu o sinal da D24, a F6a.8 (confirmação) não é executada, e a próxima fase é a F3. As lições vão para a F6 (ver "Pendências"). O item de regressão que falhou em parte (deriva do A0.1 entre jobs) foi aceito como deriva do nó, já que todas as comparações são pareadas no mesmo job.

### Opções apresentadas no gate

**Opções:**

1. **Não confirmar nada e fechar a F6a com resultado negativo** (critério da D24 aplicado como está). Levar para a F6: a A2.1 sozinha não basta, falta pesar o custo da vítima (A3), e a LVF fiel ao artigo perde por escolher vítimas ocupadas (motiva a A9.2).
2. **Confirmar só a EDF v2 com S2 no T1** (`k_T` = 10 e 25), 5 repetições pareadas contra A0.1 e A0.2, mais o C2 como controle (D24). Pergunta: o empate no combinado com ganho no pior modelo (justiça) se sustenta com IC 95 %? Custo estimado: 2 níveis de SLO × 5 rep. no T1 (~14 min/nível) + C2, ~5–6 h de cluster em 3 jobs.
3. **Opção 2 só com `k_T` = 25**, onde o ganho no pior modelo é maior (+20,5), com metade do custo.

**Recomendação do agente:** opção 1 para o critério de sinal da D24, que nenhuma configuração atingiu. A opção 3 é razoável se o Gabriel quiser a justiça como objetivo (A7/F8): é a única configuração com indício consistente de ganho de justiça sem perda no combinado. O ciclo de 1 s e a LVF não devem ir para a confirmação.

## Pendências que passam para fases seguintes

- **F6:** A3 (perda esperada da vítima), A9.2 (LVF com custo de ativação e vítima pelo valor), e a EDF com custo da vítima; reavaliar o ciclo de 1 s só com histerese maior.
- **F4:** A1.1 continua sem dados (desligada aqui, D25); C3 com A1.1.
- **Infra:** a P13 está corrigida, mas o *decode OOM* durante a drenagem mostra que a ativação do modelo que entra pode tomar o KV da vítima que ainda drena. Medir na F4.
- **Análise:** `collect_reps.py` mantém níveis que o validador marcou como inválidos (critério próprio de "limpo"); usar `f6a_triage.py`, que lê o CSV do validador, ou corrigir o `collect_reps.py`.
- **Registros:** `reports/registro/execucoes.csv` (F2.7) ainda sem as linhas da F6a (`register_runs.py`); feito junto com o commit do Gabriel, porque o hash é o do commit.

## Reproduzir

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
$PY -m unittest tests/policy/test_deadline.py tests/controller/test_decision_log.py tests/controller/test_estimators.py \
    tests/robustness/test_deactivate_evict_stuck.py tests/robustness/test_model_service_alive.py
# jobs (1 rep. por job; máx. 3 simultâneos)
PRISM_JOB_SUFFIX=-f6a-tri-c1-1 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f6a_tri_c1_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f6a-tri-t1-2b PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f6a_tri_t1_suite.tsv PRISM_TIMEOUT=14400" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f6a-edf2-c1-1 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f6a_tri_c1_edf2_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f6a-cyc1-t1-1 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f6a_cyc1_t1_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
# (idem para as outras repetições: c1-2, edf2-c1-2, edf2-t1-1, cyc1-c1-1/2, cyc1-t1-2)
# validar cada job baixado e analisar
python3 polyaxon/validate_run.py --csv reports/data/F06a/validador/<job>.csv /mnt/scratch/scheduler/prism-raw/F6a-tri/<job>
V=reports/data/F06a/validador
$PY polyaxon/f6a_triage.py reports/data/F06a/triagem $V/tri_*.csv $V/edf2_*.csv $V/cyc1_*.csv
```
