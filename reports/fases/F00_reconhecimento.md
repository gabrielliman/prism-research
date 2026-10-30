# F0 — Reconhecimento e reprodução da linha de base

Data de início / fim: 2026-10-29 / 2026-10-29
Commits: código do sistema em `2ac0098` (branch `sglang-only`), sem alterações. Arquivos novos desta fase (ainda não commitados): `polyaxon/configs/f0_repro_suite.tsv`, `polyaxon/compare_reference.py`, este relatório, `reports/fases/F00_inventario.md`, a entrada P11 em `reports/erros.md`, `reports/data/F00/`, `reports/figs/F00/`.

## Objetivo

Confirmar o ponto de partida do plano (seção 1 do `PLANO_AGENTE.md`) em vez de assumi-lo: inventariar o código (F0.1), responder se a arbitragem por folga do artigo existe (F0.2), verificar as pendências (F0.3) e reproduzir duas configurações de referência de 28/10 (F0.4).

## Hipóteses

- O código em `2ac0098` é o mesmo dos relatórios de 28/10, exceto pela R2.5 (TTFT do primeiro prefill, commitada em `e8f1b95`, depois das rodadas de referência) e pela remoção do vLLM. Esperávamos, então, reproduzir as referências dentro da variação entre repetições, talvez com TTFT um pouco menor por causa da R2.5.
- A arbitragem por Moore-Hodgson do artigo provavelmente não está no código aberto, já que os relatórios anteriores nunca a viram agir.

## Mudanças de código

Nenhuma no sistema. Infraestrutura de análise:

| Arquivo | O quê |
| --- | --- |
| `polyaxon/configs/f0_repro_suite.tsv` | suíte com A0.1, A0.2 (`ovl_phases`) e A0.3 (`ovl_trace_big`), uma repetição por job |
| `polyaxon/compare_reference.py` | compara as repetições novas com as de referência: média e [mín, máx] da referência, valores novos, se a média nova cai no intervalo e quantas repetições caem; ordem das configurações por SLO |

## Configurações executadas

| Id | Cenário | Variáveis | Referência em 28/10 |
| --- | --- | --- | --- |
| A0.1 | `ovl_phases` 0,5 req/s (10 × 8B, 5 ativos, 2 grupos de 150 s, 600 s, 1.564 requisições) | `PRISM_IDLE_THRESHOLD=50` | `original`, 4 repetições |
| A0.2 | idem | `PRISM_IDLE_THRESHOLD=10` (ciclo 5 s) | `idle10`, 3 repetições |
| A0.3 | `ovl_trace_big` escala 1 (12 × 8B, 6 ativos, trace real, 600 s, 1.275 requisições) | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_SWAP_DRAIN=1 PRISM_ACTIVATION_HEADROOM_GB=3` (P0D1) | `tp_P0D1`, 3 repetições |

Imagem `gabrielliman/prism:sglang0.3.4-cu121`, 1 H200 por job, Polyaxon `kunumi/hpc4ai`, fila `axia/default`. As sementes são as padrão do gerador (fixas), iguais às de 28/10. SLO S1: TTFT < 1 s e TPOT < 100 ms. Os 3 jobs rodaram ao mesmo tempo (2026-10-29, 20:09–20:51 UTC), cada um com as três configurações em sequência.

Também foram analisados (F0.3) 3 jobs já existentes, da folga de KV no `ovl_mix` (`polyaxon/configs/headroom_mix_suite.tsv`, 2026-10-29 de manhã), que ainda não estavam em nenhum relatório.

## Execuções

O validador (F2) ainda não existe. O status abaixo é o critério de nível limpo de `collect_reps.py` (sem abort do kvcached, `torch` OOM, `pretty_print` ou worker morto), mais perdas = 0.

| run_id (job / configuração / nível) | Status | Observação |
| --- | --- | --- |
| `3ed09648` / A0.1 / `ovl_phases` rate0.5 | limpo | SLO 73,3% |
| `8ba45f98` / A0.1 / `ovl_phases` rate0.5 | limpo | SLO 73,4% |
| `08d0f8f5` / A0.1 / `ovl_phases` rate0.5 | limpo | SLO 73,4% |
| `3ed09648` / A0.2 / `ovl_phases` rate0.5 | limpo | SLO 90,9% |
| `8ba45f98` / A0.2 / `ovl_phases` rate0.5 | limpo | SLO 90,3% |
| `08d0f8f5` / A0.2 / `ovl_phases` rate0.5 | limpo | SLO 90,9% |
| `3ed09648` / A0.3 / `ovl_trace_big` ts1 | limpo | SLO 74,4% |
| `8ba45f98` / A0.3 / `ovl_trace_big` ts1 | limpo | SLO 74,7% |
| `08d0f8f5` / A0.3 / `ovl_trace_big` ts1 | limpo, **com anomalia** | SLO 70,0%; desativação de 30 s (P11, abaixo) |
| `d01366c2` / folga 3 GB / `ovl_mix` rate0.2 | limpo | SLO 76,1% |
| `28efc238` / folga 3 GB / `ovl_mix` rate0.2 | limpo | SLO 76,1% |
| `82b3e0b9` / folga 3 GB / `ovl_mix` rate0.2 | limpo | SLO 76,1% |

Zero aborts do kvcached, zero OOM, zero workers mortos e zero perdas nas 12 execuções. Todas passaram na verificação de saúde do nó na primeira tentativa.

## Resultados

### F0.1 — Inventário

Em [`F00_inventario.md`](F00_inventario.md): árvore relevante, as 20 variáveis `PRISM_*` do sistema e as da infraestrutura com os padrões, as políticas de `simple_global.py` e a ordem das decisões num ciclo, o mapeamento A0.1–A0.5, o fluxo de ponta a ponta de uma execução e o formato de cada arquivo de log e de resultado.

Dois pontos afetam as próximas fases:
- **As políticas não são funções puras.** `gen_actions` lê o relógio e a memória da GPU e muda estado interno. A seção 0.4 do plano exige um retrato de estado e uma função pura de decisão, o que precisa de uma refatoração (sem mudar o comportamento) antes dos testes unitários de F4.
- **Os logs não são estruturados e não têm id de requisição** nos eventos de devolução ao Redis. Isso é o que impede hoje de seguir as 25 requisições perdidas (F1.2) e é o objeto de F2.1.

### F0.2 — Arbitragem por folga (Moore-Hodgson)

**Não existe no código aberto.** Detalhes e trechos em [`F00_inventario.md`, seção 4](F00_inventario.md#4-f02--a-arbitragem-por-folga-moore-hodgson-no-código-aberto). Em resumo:
- a fila por GPU (`gpu/request_queue.py`) ordena por `chegada + SLO − prefill estimado` (EDF ajustado), mas não faz o passo de remoção da requisição mais longa do Algoritmo 2;
- a admissão por recursos está desligada (`net_available = float("inf")`, `request_queue.py:137`);
- o motor SGLang atende a sua fila em FCFS (radix cache desligado), e o descarte por SLO (`--abort-exceed-slos`) não está ativo;
- com o SLO igual para todas as requisições nos cenários `ovl_*`, a ordem da fila é quase a de chegada.

Consequência: **A0.5 precisa ser implementada** (F7.4) antes de A6, como o plano já prevê.

### F0.3 — Estado das pendências

| Pendência | Estado em 2026-10-29 | Evidência |
| --- | --- | --- |
| T1 com 14 modelos | **aberta.** Reproduzido em 28/10 (parada de 324 s na versão corrigida, 1 de 2 na base); causa não confirmada para 14 modelos; nenhum `py-spy` coletado | `reports/2026-10-28 Limites de carga...`, seção T1; `reports/erros.md` |
| Folga de KV no `ovl_mix` (A0.4) | **3 de 5 repetições feitas, não reportadas.** A folga sozinha evita o travamento: SLO de 76% (76–76) contra 2,6% da original, zero perdas. Mas não resolve a fome: o `model_6` e o `model_7` ficam com 0% de SLO, com pior espera de 342 s (a troca P0D1 dá 51% de SLO e pior espera de 53 s). Faltam 2 repetições para F1.3 | `reports/data/F00/folga_ovl_mix/metricas.csv`, `reports/figs/F00/folga_ovl_mix/` |
| 25 requisições perdidas (P1D0, trace12) | **aberta**, sem causa; os logs não têm id para seguir a requisição | `reports/2026-10-28 Janela de ociosidade...`, seção 4 |
| K1 (abort do kvcached) | **mitigado, não eliminado.** 0 aborts nas 12 execuções desta fase, com o nó saudável; em 27/10 (nó degradado) ainda houve aborts | `reports/erros.md`; esta fase |
| P11 (nova) | **aberta:** desativação de ~30 s sem trabalho pendente (abaixo) | seção Anomalias |

Tabela da folga de KV (`python3 polyaxon/report_tables.py reports/data/F00/folga_ovl_mix/metricas.csv ovl_mix/rate0.2`; original e P0D1 de `reports/data/2026-10-28-ociosidade/metricas.csv`):

| Configuração | Rep. | Atendidas | Perdas | TTFT p50 / p99 (s) | TTFT p90 (s) | SLO (%) | Pior espera pelo 1º token (s) | Ativações |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| original (50 s) | 3 | 2,6% | 1605 (536, 536, 533) | 0,12 / 9,4 | 2,1 (1,3–3,4) | 2 (2–2) | nunca | 2 |
| só folga de 3 GB | 3 | 100,0% | — | 0,18 / 333,6 | 225,3 (222,1–227,2) | 76 (76–76) | 342 (341–343) | 3 |
| troca P0D1 | 3 | 100,0% | — | 1,14 / 58,2 | 36,1 (33,3–40,1) | 51 (46–56) | 53 (39–73) | 38 |

### F0.4 — Reprodução

Saída de `polyaxon/compare_reference.py` (completa em `reports/data/F00/reproducao/comparacao.md`). SLO em %, tempos em s.

| Configuração | Métrica | Referência: média [mín, máx] | Nova: média (repetições) | No intervalo |
| --- | --- | --- | --- | --- |
| A0.1 | SLO | 71,5 [69,0; 73,3] | 73,4 (73,3; 73,4; 73,4) | **não** (acima do máximo por 0,1) |
| A0.1 | TTFT p90 | 33,6 [32,3; 34,3] | 33,0 | sim |
| A0.1 | TTFT p99 | 54,5 [53,7; 55,4] | 53,4 | **não** (abaixo do mínimo por 0,3) |
| A0.1 | pior espera | 58,4 [57,4; 59,1] | 58,4 | sim |
| A0.1 | ativações / perdas | 15 / 0 | 15 / 0 | sim |
| A0.2 | SLO | 86,7 [80,8; 90,4] | 90,7 (90,9; 90,3; 90,9) | **não** (acima do máximo por 0,3) |
| A0.2 | TTFT p90 | 2,4 [0,3; 5,1] | 0,5 | sim |
| A0.2 | TTFT p99 | 20,8 [20,4; 21,3] | 20,0 | **não** (abaixo do mínimo por 0,4) |
| A0.2 | pior espera | 21,8 [20,8; 23,6] | 21,8 | sim |
| A0.2 | ativações / perdas | 15,7 [15; 16] / 0 | 16,3 (16; 16; 17) / 0 | **não** / sim |
| A0.3 | SLO | 72,3 [71,7; 73,1] | 73,0 (74,4; 74,7; 70,0) | sim (média), 0/3 repetições |
| A0.3 | TTFT p90 | 27,7 [26,4; 28,7] | 26,9 | sim |
| A0.3 | TTFT p99 | 71,3 [60,1; 78,2] | 66,1 | sim |
| A0.3 | pior espera | 50,0 [48,1; 53,7] | 58,7 (48,2; 48,3; 79,7) | **não** (r3, P11) |
| A0.3 | ativações / perdas | 66,7 / 0 | 66,0 / 0 | sim |

**Ordem entre políticas** no `ovl_phases`: A0.2 > A0.1 nas duas campanhas (90,7% contra 73,4% agora; 86,7% contra 71,5% antes), com a mesma diferença de pior espera (22 s contra 58 s).

**Por que as médias novas ficam no topo ou um pouco acima da referência.** As repetições de referência vêm de três rodadas (`manifest.csv` de 28/10). As mais baixas são as da rodada `fix3`, que rodou num período de nó degradado (relatório de 28/10, "De onde vêm os dados"). Nelas, as ativações foram mais lentas e mais requisições ficaram com TTFT entre 1 e 15 s:

| Configuração | Repetição (rodada) | SLO (%) | Ativação média / máxima (s) | Requisições com TTFT em [1, 15) s |
| --- | --- | --- | --- | --- |
| original | r1 (`fix3`) | 69,0 | 2,7 / 8,6 | 187 |
| original | r2–r4 (`fix2`) | 71,2–73,3 | 2,0–2,2 / 3,9–4,4 | 142–148 |
| A0.1 nova | r1–r3 | 73,3–73,4 | 2,1–2,2 / 3,9–4,1 | 138–141 |
| idle10 | r2 (`fix3`) | 80,8 | 2,1 / 4,0 | 168 |
| idle10 | r1 (`fix5`), r3 (`fix2`) | 89,1, 90,4 | 1,7–1,9 / 3,7–4,3 | 111–130 |
| A0.2 nova | r1–r3 | 90,3–90,9 | 1,7–1,8 / 3,5–4,0 | 106–111 |

Sem as repetições `fix3`, a referência do A0.1 seria [71,2; 73,3] e a do A0.2 [89,1; 90,4], e os valores novos ficam a 0,1–0,3 ponto do máximo (1 a 5 requisições em 1.564). Testamos e descartamos a outra explicação candidata, a R2.5: as retiradas no decode somam 0–4 requisições por execução nas duas campanhas, pouco para explicar a diferença.

**Sobre o critério.** O plano pede "métricas principais dentro do intervalo observado". Com 3 repetições de referência, uma nova execução da **mesma** distribuição cai fora do intervalo [mín, máx] com probabilidade 2/(n+1) = 50% por métrica, só por acaso. Com seis métricas e três configurações, o critério estrito quase sempre falharia mesmo numa reprodução perfeita. Não o relaxamos (seção 0.1.4 do plano): registramos a falha e deixamos a decisão para a revisão (abaixo).

## Anomalias e investigações

### P11 — Desativação de ~30 s sem trabalho pendente (A0.3, r3, job `08d0f8f5`)

1. **Sintoma.** Pior espera pelo 1º token de 79,7 s (`model_12`), contra 48,2 e 48,3 s nas outras repetições e [48,1; 53,7] na referência. SLO de 70,0%, contra 74,4–74,7%.
2. **Linha do tempo** (figura `reports/figs/F00/reproducao/ovl_trace_big__A0.3_trace12__r3__ts1.png`):
   - t = 20 s: a troca escolhe `model_2` (para `model_11`) e `model_6` (para `model_7`), nas três repetições, de forma idêntica;
   - r1 e r2: as duas desativações confirmam em ~1 s; `model_7` e `model_11` entram em t = 25 s; a troca seguinte (t = 50 s) escolhe o `model_12`, que entra em t = 55 s;
   - r3: as duas desativações levam **29,97 s e 30,33 s** dentro de `WorkerPoolModelRunner.deactivate()` (`worker_pool_model_runner.py:453`). O log do worker mostra fila vazia, lote em execução vazio e drenagem de 0,00 s (`In handle deactivate request, waiting queue size: 0. Running batch size: 0`; `Drained for 0.00 s`; `Deactivate time cost: 29.9623s`). A memória só aparece em t = 50 s, `model_7` e `model_11` entram em t = 52–56 s, e o `model_12`, que ficou atrás deles, só entra em t = 77 s.
3. **Hipóteses testadas e descartadas:** (a) requisições em decode nas vítimas — nenhuma em execução em t = 20,5 s nas três repetições (`requests.csv`); (b) execução mais lenta como um todo — TPOT p50 de 48,7 ms no r3, contra 46,5–46,6 ms (r1, r2) e 48,4–50,2 ms na referência.
4. **Frequência.** Nas 9 execuções desta fase e nas 3 da folga de KV, `deactivate()` passou de 5 s em **2 das 197** desativações do A0.3 (nenhuma das 103 do A0.1/A0.2 nem das 26 da folga de KV), as duas no mesmo instante do r3. As demais desativações longas do A0.3 (26–28 por execução acima de 5 s, entre a decisão e a confirmação) são drenagem legítima (até 15 s) de vítimas com requisições em execução, e já existiam na referência (30–35 por execução).
5. **Classificação.** Falha nova (P11 em `reports/erros.md`), de desempenho, sem perda de requisição. A causa ainda não foi identificada; as candidatas são a liberação do pool do kvcached (`token_to_kv_pool.release()`), o `gc.collect()` ou o `empty_cache()` concorrendo com a carga de pesos de outro modelo pelo model service, ou ainda as duas liberações simultâneas. Ela não invalida a execução (não é falha de sistema pelos critérios atuais), mas explica a diferença do r3.
6. **Próximo passo (F1):** instrumentar `deactivate()` com o tempo de cada etapa e reproduzir com duas desativações simultâneas durante uma ativação.

**Investigação aberta:** P11. Pela seção 0.3.6 do plano, ela bloqueia o gate até ser resolvida ou até o Gabriel decidir passá-la para a F1.

## Critérios de aceitação

| Critério | Resultado | Evidência |
| --- | --- | --- |
| Inventário completo e revisado | OK do lado do agente; **falta a revisão** | `reports/fases/F00_inventario.md` |
| Resposta documentada sobre a arbitragem por folga | OK: não existe; A0.5 precisa ser implementada | `F00_inventario.md`, seção 4 |
| Reprodução: mesma ordem entre políticas | OK | seção F0.4 |
| Reprodução: métricas principais dentro do intervalo observado | Aceita pelo Gabriel (D1). **FALHOU no critério estrito**: SLO do A0.1 (+0,1) e do A0.2 (+0,3) acima do máximo; TTFT p99 do A0.1 e do A0.2 abaixo do mínimo (−0,3 e −0,4 s); ativações do A0.2 (+0,3); pior espera do A0.3 (r3, P11). Todas as diferenças, menos a do r3, vão no sentido "melhor" e se explicam pelas repetições `fix3` da referência; a do r3 é a P11 | `reports/data/F00/reproducao/comparacao.md`; seção F0.4 |

## Decisão do gate: APROVADO (Gabriel, 2026-10-30)

Respostas às três perguntas da revisão (registradas em `reports/registro/decisoes.md`):

1. **Reprodução aceita** (D1).
2. **Critério novo** (D2): IC 95% por bootstrap da diferença de médias contendo 0, no SLO, no TTFT p90 e na pior espera, sem as repetições `fix3`. Aplicado aos dados desta fase (`python3 polyaxon/compare_reference.py --exclude-round fix3 ...`, saída em `reports/data/F00/reproducao/comparacao_criterio_bootstrap.md`), ele falha em 3 das 9 comparações, com diferenças pequenas e no sentido "melhor":

   | Configuração | Métrica | Referência sem `fix3` | Nova | Diferença [IC 95%] | Critério |
   | --- | --- | --- | --- | --- | --- |
   | A0.1 | SLO (%) | 72,3 (71,2–73,3) | 73,4 | +1,1 [+0,1; +2,2] | FALHOU |
   | A0.1 | TTFT p90 (s) | 33,3 | 33,0 | −0,4 [−1,3; +0,6] | OK |
   | A0.1 | pior espera (s) | 58,5 | 58,4 | −0,0 [−1,0; +1,0] | OK |
   | A0.2 | SLO (%) | 89,7 (89,1–90,4) | 90,7 | +1,0 [+0,1; +1,8] | FALHOU |
   | A0.2 | TTFT p90 (s) | 1,1 | 0,5 | −0,6 [−1,4; +0,3] | OK |
   | A0.2 | pior espera (s) | 21,0 | 21,8 | +0,8 [−0,3; +2,6] | OK |
   | A0.3 | SLO (%) | 72,4 (71,7–73,1) | 73,0 | +0,6 [−2,4; +2,9] | OK |
   | A0.3 | TTFT p90 (s) | 28,3 | 26,9 | −1,4 [−2,0; −0,8] | FALHOU |
   | A0.3 | pior espera (s) | 51,0 | 58,7 | +7,7 [−5,5; +28,7] | OK |

   Com 2–3 repetições por lado, o bootstrap subestima a variância e rejeita diferenças pequenas; o teste de permutação não rejeitaria nada (p mínimo de 0,10). A aceitação (item 1) não muda. Para a F1.5, o agente propõe 5 repetições novas contra as 3 desta fase como referência (D2, pendente de confirmação).
3. **P11 vai para a F1** (D3), como tarefa F1.7.

Também nesta revisão: o Gabriel pediu a avaliação do Virtual Lag Time do SuperInfer, que entrou no plano como a família A9 (D4; seção A9 do `PLANO_AGENTE.md`, tarefas F6.10–F6.12).

## Pendências que passam para fases seguintes

- F1.1: T1 com 14 modelos (reprodução mínima + `py-spy`).
- F1.2: 25 requisições perdidas; exige id de requisição nos logs de devolução ao Redis.
- F1.3: folga de KV no `ovl_mix`, faltam 2 repetições (3 de 5 feitas; resultado acima).
- F1.4: K1 (0 ocorrências nesta fase).
- F1.7 (nova): P11, desativação de ~30 s.
- Antes de F4 (testes unitários): separar retrato de estado e função de decisão em `simple_global.py`, sem mudar o comportamento.
- F7.4: implementar A0.5 (Moore-Hodgson), que não existe no código aberto.

## Como reproduzir

```bash
# F0.4: três jobs, uma repetição cada (cerca de 42 min cada)
for r in 1 2 3; do
  PRISM_JOB_SUFFIX=-f0-repro-$r PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f0_repro_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh
done
# baixar cada job numa pasta própria (<uuid> de `polyaxon ops ls -p kunumi/hpc4ai`)
polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path <dl>/f0-repro-<r>
# juntar, resumir, comparar com 28/10 e gerar as linhas do tempo (pandas/matplotlib: /mnt/scratch/scheduler/opt-env/bin/python)
python3 polyaxon/collect_reps.py reports/data/F00/reproducao f0=<dl>
python3 polyaxon/summarize_reps.py reports/data/F00/reproducao
python3 polyaxon/compare_reference.py reports/data/F00/reproducao/metricas.csv reports/data/2026-10-28-ociosidade/metricas.csv \
  ovl_phases/rate0.5/A0.1_phases=ovl_phases/rate0.5/original ovl_phases/rate0.5/A0.2_phases=ovl_phases/rate0.5/idle10 \
  ovl_trace_big/ts1/A0.3_trace12=ovl_trace_big/ts1/tp_P0D1
# critério da decisão D2 (mesmos pares, sem as repetições fix3 da referência)
python3 polyaxon/compare_reference.py --exclude-round fix3 reports/data/F00/reproducao/metricas.csv \
  reports/data/2026-10-28-ociosidade/metricas.csv <mesmos pares> > reports/data/F00/reproducao/comparacao_criterio_bootstrap.md
python3 polyaxon/plot_suite.py reports/data/F00/reproducao reports/figs/F00/reproducao
# F0.3: folga de KV no ovl_mix (jobs d01366c2, 28efc238, 82b3e0b9; pastas headroom-mix-<r>)
python3 polyaxon/collect_reps.py reports/data/F00/folga_ovl_mix fix5=<dl headroom>
python3 polyaxon/summarize_reps.py reports/data/F00/folga_ovl_mix
python3 polyaxon/report_tables.py reports/data/F00/folga_ovl_mix/metricas.csv ovl_mix/rate0.2
# P11: tempos de desativação no worker
grep -oE "TP=0\] Deactivate time cost: [0-9.]+" <dl>/f0-repro-3/outputs/A0.3_trace12/ovl_trace_big/ts1/server_file.log
```

| Job | uuid |
| --- | --- |
| f0-repro-1 | `3ed09648324941d7afd98087e0a6cc5a` |
| f0-repro-2 | `8ba45f987f094e338d3afe329cd6782b` |
| f0-repro-3 | `08d0f8f54b5c482fa19d4e54278f4379` |
| headroom-mix-1/2/3 | `d01366c28da5409cad1a5be3501d19e0`, `28efc23841f747ba879cccaf3fa49818`, `82b3e0b98cf949e7b5f1c260e464e2dc` |
