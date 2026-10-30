# F1 — Fechar a robustez restante

Data de início / fim: 2026-10-30 / 2026-10-30
Commits: código do sistema em `2ac0098` (branch `sglang-only`) mais a instrumentação desta fase, ainda não commitada. A instrumentação fica desligada por padrão, com uma exceção: a linha de log da desativação ganhou o tempo de cada etapa.

## Objetivo

Fechar as pendências de robustez herdadas da F0 (seção F1 do `PLANO_AGENTE.md`):
- F1.1: travamento T1 com 14 modelos;
- F1.2: as 25 requisições perdidas;
- F1.3: folga de KV no `ovl_mix`;
- F1.4: K1;
- F1.7: desativação lenta (P11).

Depois, repetir a F0.4 para confirmar que nada regrediu (F1.5).

## Hipóteses

- **T1:** os workers ficam bloqueados esperando páginas de KV que ninguém libera. O relatório de 28/10 levantou a hipótese sem confirmá-la.
- **25 perdas:** alguma requisição se perde no caminho de devolução ao Redis durante a preempção.
- **P11:** alguma etapa de `deactivate()`, ainda não identificada.
- **F1.5:** como nenhuma mudança altera o comportamento padrão, a F0.4 deveria se reproduzir.

## Mudanças de código

Todas ficam atrás de variáveis de ambiente desligadas por padrão. A exceção é a linha de log da desativação, que passou a mostrar o tempo de cada etapa.

| Arquivo | O quê | Variável |
| --- | --- | --- |
| `python/sglang/srt/model_executor/worker_pool_model_runner.py` (`deactivate`) | tempo de cada etapa (`release`, `delete_model`, `gc`, `empty_cache`) na linha "Deactivate time cost"; despejo da pilha de todas as threads se a desativação passar de N s | `PRISM_DEACTIVATE_DUMP_S` (0) |
| `python/sglang/multi_model/request_handler_worker_pool.py`, `scheduling/gpu/gpu_scheduler.py`, `srt/managers/scheduler.py` | linha `RID <passagem> <modelo> <rid>` em cada passagem da requisição entre o request handler, o GPU scheduler, as filas do Redis e os workers | `PRISM_TRACE_RIDS` (0) |
| `python/sglang/multi_model/stack_dump.py` (novo), chamado pelo worker e pelo GPU scheduler | pilhas Python de todas as threads ao receber SIGUSR1 (`faulthandler`), cada processo no seu arquivo | `PRISM_STACK_DUMPS` (0) |
| `polyaxon/run_examples.sh` | envia SIGUSR1 nos instantes pedidos e recolhe as pilhas em `<nível>/stacks/` | `PRISM_STACK_DUMP_AT` |
| `polyaxon/collect_reps.py` | número de repetições guardadas por configuração configurável | `PRISM_REPS` (3) |
| `polyaxon/trace_rids.py` (novo) | caminho de cada requisição não atendida, a partir das linhas `RID` | — |
| `polyaxon/stack_summary.py` (novo) | resumo das pilhas: quadros mais internos da thread principal em cada despejo | — |
| `polyaxon/compare_reference.py` | critério D2 (IC 95% por bootstrap, `--exclude-round`) | — |
| `python/sglang/multi_model/memory_arbiter.py`, `model_sevice.py`, `srt/model_executor/worker_pool_model_runner.py`, `srt/managers/scheduler.py`, `scheduling/gpu/gpu_scheduler.py`, `scheduling/controller_global.py` | P12: o model service grava o PID e sobrevive a um pedido que não consegue receber; o worker espera em fatias de 1 s e reverte a ativação (`ModelServiceUnavailable`, subclasse de `ActivationFailed`) se o serviço morreu ou não respondeu; o GPU scheduler avisa o controlador (`model_service_lost`), que para de ativar e despejar | `PRISM_DETECT_DEAD_MODEL_SERVICE` (**1**, como a P2; só muda o comportamento quando o model service falha) |
| `polyaxon/run_examples.sh` | falha injetada `PRISM_FAULT=kill_model_service:<s>` | — |
| `tests/robustness/test_model_service_alive.py` (novo) | PID vivo, morto, zumbi e não registrado; hierarquia das exceções de ativação (5 testes) | — |

Usamos `faulthandler` em vez de `py-spy`, porque o `py-spy` precisaria de permissão de ptrace dentro do contêiner. O `faulthandler` também despeja a pilha de um processo parado dentro de uma chamada C.

## Configurações executadas

| Suíte | Jobs | Para quê |
| --- | --- | --- |
| `headroom_mix_suite.tsv` | `f1-headroom-mix-4/5` (`97573c2b`, `4b133f88`) | F1.3: 2 repetições que faltavam |
| `f1_trace_suite.tsv` | `f1-trace-1..3` (`09081d58`, `aa9cf3b3`, `4a14245b`) | F1.2/F1.7: P1D0 e P0D1 com rastreio por `rid` e despejo de pilha. **Inválida (D6)** |
| `f1_freeze_suite.tsv` | `f1-freeze-1/2` (`95394674`, `566bb4f1`), com pilhas a 45/90/180 s; `f1-freeze-3/4` (`883ec25a`, `1e22020e`), com pilhas a 120/240/360/480 s | F1.1: `ovl_mem` com 8 e 14 modelos, política original |
| `f1_ab_suite_a/b.tsv` | `f1-ab-1..3` (`6c3ff6b5`, `d7d4e7f9`, `41a305c3`) | A0.3 com e sem a instrumentação, ordem alternada |
| `f1_loss_suite.tsv` | `f1-loss-1..5` (`8997f0a2`, `af079260`, `5104cd7a`, `96652434`, `9213b523`) | F1.2: 10 repetições da troca P1D0 com rastreio |
| `f0_repro_suite.tsv` | `f1-repro-1..5` (`3247ebf0`, `1c2449f8`, `8e766a87`, `fb5d05f5`, `254fc4c4`) | F1.5: repetição da F0.4, 5 repetições |
| `f1_p12_on/off_suite.tsv` | `f1-p12-on/off` (`517ccd66`, `808894d8`), `f1-p12b-on/off` (`e94ae6fd`, `580b323d`) | P12: A0.3 com o model service morto a 120 s, com e sem a correção, no mesmo período |
| `f1_codeab_suite.tsv` | `f1-code-old-1..3` (código `2ac0098`, via `PRISM_PYTHON_SRC`) e `f1-code-new-1..3` (código atual), ao mesmo tempo | F1.5: separar regressão de código de mudança no cluster |

Ambiente:
- imagem `gabrielliman/prism:sglang0.3.4-cu121`;
- 1 H200 por job;
- Polyaxon `kunumi/hpc4ai`, fila `axia/default`;
- sementes padrão do gerador;
- SLO S1: TTFT < 1 s e TPOT < 100 ms.

## Execuções

O validador da F2 ainda não existe. "Limpa" segue o critério de `collect_reps.py`: sem abort do kvcached, `torch` OOM, `pretty_print` ou worker morto. Somamos a isso a ausência de morte do model service.

| Jobs | Execuções | Limpas | Observação |
| --- | --- | --- | --- |
| `f1-headroom-mix-4/5` | 2 | 2 | — |
| `f1-trace-1..3` | 6 | 0 | **INVALIDA_INFRA** (D6). K1 em 5 execuções, morte do model service (P12) em 4, workers mortos. A janela de 00:31 a 00:54Z coincide com falhas da verificação de partida do kvcached com a GPU vazia nos jobs `f1-freeze-1/2` |
| `f1-freeze-1/2` | 4 | 2 | O nível de 8 modelos não subiu: a verificação de partida do kvcached falhou 3 vezes, ainda na janela degradada. Os 14 modelos subiram e travaram |
| `f1-freeze-3/4` | 4 | 4 | as 4 travaram (é o fenômeno estudado, não uma falha de infraestrutura) |
| `f1-ab-1..3` | 6 | 6 | 0 perdas nos dois braços |
| `f1-loss-1..5` | 10 | 10 | 4 com requisições não atendidas, todas explicadas (F1.2) |
| `f1-repro-1..5` | 15 | 15 | 0 perdas; critério de reprodução FALHOU (F1.5) |
| `f1-code-*` | 6 | 6 | 0 perdas |

## Resultados

### F1.3 — Folga de KV no `ovl_mix` (A0.4)

5 repetições, todas limpas e idênticas: 100% atendidas, SLO de 76%, pior espera pelo 1º token de 342 s, 3 ativações.
- A folga sozinha evita o travamento da política original, que atende só 2,6%.
- Mesmo assim, o `model_6` e o `model_7` passam fome até a carga acabar. Os 8 modelos ativos nunca ficam 50 s ociosos, então nada é despejado.
- É uma consequência da política, e é o caso que a A1 (F4) e a A9/A2 (F6) devem atacar.

Dados em `reports/data/F01/folga_ovl_mix/`; linhas do tempo em `reports/figs/F01/folga_ovl_mix/`.

### F1.1 — T1: impasse de memória causado pela política

Nos jobs `f1-freeze-3/4`, as pilhas despejadas durante o travamento (`reports/data/F01/travamento/*_pilhas.txt`) mostram:
- os workers ativos no ramo ocioso do laço do scheduler (`scheduler.py:488`, sem lote para rodar);
- os inativos em `:494`;
- **nenhum processo parado no driver.**

A GPU está fisicamente cheia: 142,4 de 143,8 GB com 8 modelos e 135,7 GB com 14 (linhas do tempo em `reports/figs/F01/travamento/`). A sequência:
1. não há página para o KV de nenhum prefill;
2. nenhuma requisição roda, então nada libera memória;
3. a política original não despeja, porque todo modelo tem fila e nunca fica 50 s ocioso.

Os workers param de registrar porque o ramo ocioso não registra nada. Nos jobs `f1-freeze-1/2` isso parecia uma parada do driver, já que as pilhas daqueles jobs caíram todas antes do travamento.

**Por que 14 travam com ~7 GB livres** (dúvida em aberto desde 28/10):
- o kvcached deixa 5% da GPU fora do KV (`GPU_UTILIZATION = 0.95`, `kvcached/slab_allocator.py:40`), ou seja, 7,2 GB;
- com 14 modelos, o controlador para de ativar com ~7 GB livres, abaixo desse limiar;
- a conta de memória do controlador (R2.1) não inclui essa reserva.

Encaminhado para a F4: A1.1 (reserva de KV na ativação, que deve somar a reserva do kvcached) e A1.2 (detector de impasse).

### F1.2 — As 25 perdas: requisições presas em ciclo, nenhuma descartada

Nas 10 repetições limpas da troca P1D0 com rastreio por `rid`, 4 tiveram requisições não atendidas no prazo da carga (26, 6, 3 e 20). `polyaxon/trace_rids.py` reconstrói o caminho de cada uma (`reports/data/F01/perdas/`):

| Causa | Requisições | Mecanismo |
| --- | --- | --- |
| ciclo de preempção | 54 | iniciadas e preemptadas 3 vezes ou mais; a cada troca recomeçam do prompt (RECOMPUTE). São longas: saída de 513 tokens ou mais, contra mediana de 226 nas atendidas |
| modelo nunca reativado | 1 | a requisição 1216 do `model_4` foi devolvida à fila 1 s antes de o modelo ser desativado, e o modelo não voltou até o fim |

Todas terminam numa fila (frontend, backend, ou devolvidas por um worker); nenhuma desaparece. É consequência da política P1D0, que preempta com recomputação sem limite. Encaminhado para F4 (A1.3, histerese) e F6 (A3, drenar ou preemptar). O A0.3 usa P0D1, que não preempta.

### F1.4 — K1

| Execuções | Com K1 |
| --- | --- |
| fora da janela degradada de 2026-10-30 (00:31–00:54Z) | 0 de 37 |
| dentro da janela | 5 de 6 |

O árbitro entre processos continua desligado (D5).

### F1.7 — P11: a liberação do KV no kvcached

O tempo por etapa de `deactivate()` põe quase todo o atraso em `token_to_kv_pool.release()`. As pilhas despejadas após 10 s mostram onde: `kv_allocator.trim()` do kvcached chama `unmap_from_kv_tensors`, que desfaz o mapeamento das páginas em código C.

| Rodada | Desativações | Lentas | Maior |
| --- | --- | --- | --- |
| limpas, F1.5 | 986 | 18 acima de 10 s | 30 s |
| limpas, A/B | 778 | 5 acima de 5 s | 7,6 s |
| janela degradada | 392 | 51 acima de 5 s | 88 s |

Na janela degradada, a GPU inteira para durante a liberação lenta: utilização de ~6%, contra 87% nas liberações normais.
- **Situação:** o kvcached não é alterado. A P11 passa a ser um custo de desativação, e a F2.3 deve medir a distribuição e não só a média.
- **Validador:** a P11 não serve como sinal de nó degradado, porque também ocorre em execuções limpas.

### P12 — Morte do model service: detectada e contida (corrigida)

Na janela degradada, o model service morreu com CUDA OOM ao abrir o tensor CUDA compartilhado de um modelo (`model_sevice.py:261`). Depois disso, toda ativação esperava 300 s e falhava, e os workers morriam.

A correção (D9) está descrita em "Mudanças de código". Para verificá-la, matamos o model service a 120 s no A0.3, com e sem a correção, no mesmo período:

| Versão | Workers mortos | Timeouts de 300 s | Atendidas antes / depois da morte |
| --- | --- | --- | --- |
| sem a correção (`f1-p12b-off`) | 11 | 33 | 214 / 182 |
| só a falha rápida (`f1-p12-on`) | 0 | 0 | 213 / 55 |
| final (`f1-p12b-on`) | 0 | 0 | 213 / 605 |

A versão só com a falha rápida tinha um efeito colateral: a cada ciclo, a troca por throughput despejava vítimas para ativações que agora falhavam na hora, e a GPU ficou sem nenhum modelo ativo em cerca de 2 minutos. Com o aviso ao controlador (`model_service_lost`), ele congela ativações e despejos, e os modelos ativos continuam servindo. Uma execução em que o model service morre continua inválida para os agregados; a correção só evita a cascata.

### F1.5 — Repetição da F0.4: o critério FALHOU, por mudança no cluster

As 15 execuções ficaram limpas e sem perdas, mas ficaram abaixo da F0.4. Ordem entre as políticas: igual.

| Config | Métrica | F0.4 (3 rep.) | F1.5 (5 rep.) | Diferença [IC 95%] | Critério D2 |
| --- | --- | --- | --- | --- | --- |
| A0.1 | SLO (%) | 73,4 | 66,3 (58,7–73,6) | −7,1 [−12,4; −1,8] | FALHOU |
| A0.1 | TTFT p90 (s) | 33,0 | 34,4 | +1,4 [−0,5; +3,3] | OK |
| A0.1 | pior espera (s) | 58,4 | 61,7 | +3,2 [−0,2; +8,4] | OK |
| A0.2 | SLO (%) | 90,7 | 81,8 | −8,9 [−12,2; −6,1] | FALHOU |
| A0.2 | TTFT p90 (s) | 0,5 | 7,1 | +6,6 [+4,4; +8,8] | FALHOU |
| A0.2 | pior espera (s) | 21,8 | 25,3 | +3,5 [+0,1; +6,9] | FALHOU |
| A0.3 | SLO (%) | 73,0 | 63,6 | −9,4 [−15,6; −3,5] | FALHOU |
| A0.3 | TTFT p90 (s) | 26,9 | 37,4 | +10,5 [+5,6; +18,6] | FALHOU |
| A0.3 | pior espera (s) | 58,7 | 64,2 | +5,4 [−14,3; +22,2] | OK |

Contra a referência de 28/10 sem `fix3`, falha nas mesmas métricas (`reports/data/F01/reproducao/comparacao_ref_*.md`).

**Investigação.**
1. **Sintoma:** o decode está mais lento em todas as execuções da F1, inclusive no A/B limpo. A mediana do TPOT no A0.1 foi de 41,5 ms na F0.4 para 46–54 ms na F1.5. Com o decode mais lento:
   - a drenagem demora;
   - a memória demora a liberar;
   - a ativação espera mais. No A0.1, ela passou de 2,9–3,8 s de média e no máximo 11 s para 4,5–11,7 s e até 39 s.

   A cópia dos pesos pelo model service não mudou (~1 s), e o estado da GPU no início do job também não (H200, P0, ~33 °C, ~77 W).
2. **Hipótese A, regressão de código:** nenhuma mudança ligada por padrão está no caminho de cada token. Para testar, rodamos ao mesmo tempo 3 jobs com o código da F0.4 (`2ac0098`) e 3 com o código atual, só o A0.1 (`reports/data/F01/ab_codigo/`).
   - Os dois braços ficaram igualmente lentos: TPOT de 44,5–50,0 ms no código antigo e de 44,6–46,4 ms no atual.
   - O código atual passou no critério D2 contra o antigo: SLO +5,2 [−0,7; +12,1], TTFT p90 −0,7 [−2,6; +0,8], pior espera −2,5 [−11,6; +5,4].
   - **Refutada.**
3. **Hipótese B, cluster mais lento em 2026-10-30 do que em 2026-10-29:** consistente com tudo acima. A análise do cluster feita em paralelo pelo Gabriel (`reports/2026-10-30 Variação de desempenho do nó GPU do cluster.md`) mostra que a fila é um único nó de 8 H200 compartilhado com outras equipes e que a lentidão de ~10% no decode na manhã de 30/10 não tem causa conhecida.

**Consequência para a metodologia.** Entre dois dias, o mesmo código e a mesma configuração variaram 7 a 9 pontos de SLO. Comparar com uma referência de outro dia mede o cluster, não a política. O C-V3 do plano já pede as linhas de base "rodadas na mesma campanha"; a F1.5 mostra que isso é necessário, e não só uma boa prática. Propostas para a F2:
- registrar a velocidade do cluster em cada execução: mediana do TPOT com um modelo sozinho, num teste curto antes da carga;
- usar esse valor como covariável;
- validar as comparações sempre pareadas no mesmo período.

## Anomalias e investigações

| Anomalia | Causa | Correção | Verificação |
| --- | --- | --- | --- |
| Rodada `f1-trace`: 0 de 6 limpas | janela de nó degradado (00:31–00:54Z), que coincide com 5 jobs desta fase no nó ao mesmo tempo; com 5 ou mais jobs, as falhas de driver aparecem em 71–79% dos níveis (análise do cluster) | nenhuma no código; rodada inválida (D6); no máximo 3 jobs ao mesmo tempo daqui em diante | A/B `f1-ab-*`, mesmo código, 6 de 6 limpas; 0 K1 nas 37 execuções fora da janela |
| P12, morte do model service | CUDA OOM na janela degradada | detecção, reversão da ativação e congelamento do controlador (D9) | `f1-p12b-on/off`; testes em `tests/robustness/` |
| F1.5 abaixo da referência | cluster mais lento; regressão de código refutada | nenhuma no código; proposta de metodologia | A/B de código `f1-code-*` |
| Afirmação errada corrigida: "P11 ≤ 7,6 s com nó saudável" | tirada só das 778 desativações do A/B | corrigida em `erros.md` e D6 com os dados da F1.5 | 18 de 986 acima de 10 s em execuções limpas |
| Afirmação errada corrigida: "T1 é a mesma parada do driver da P11" | as pilhas de `f1-freeze-1/2` caíram antes do travamento | pilhas mais tarde (`f1-freeze-3/4`) | ramo ocioso, nenhum processo no driver |

## Critérios de aceitação

| Critério | Resultado | Evidência |
| --- | --- | --- |
| Causa de cada pendência identificada e registrada em `erros.md` | OK. T1: impasse de memória da política (vai para a F4). 25 perdas: ciclo de preempção e um modelo nunca reativado. K1: só com nó degradado. P11: unmap do kvcached. P12: nova, registrada | `reports/erros.md`; seções acima |
| Zero perdas não explicadas em 10 repetições da configuração que antes perdia requisições | OK. 55 não atendidas, todas explicadas, nenhuma descartada | `reports/data/F01/perdas/` |
| Nenhuma regressão: a F0.4 repetida continua dentro da referência | Contra as referências de outro dia, **FALHOU** (cluster mais lento). No A/B de código no mesmo período (critério D8), OK. Aceito pelo Gabriel (D7) | `reports/data/F01/reproducao/`, `reports/data/F01/ab_codigo/` |

## Decisão do gate: APROVADO (Gabriel, 2026-10-30)

O último critério tinha falhado e o agente parou. Respostas do Gabriel, registradas em `reports/registro/decisoes.md`:

1. **F1.5 aceita** com base no A/B de código no mesmo período (D7).
2. **"Sem regressão" e C-V3 passam a usar execuções pareadas no mesmo período** (D8), também incluído no C-V3 do `PLANO_AGENTE.md`.
3. **P12 implementada já** (D9), e verificada acima.

## Pendências que passam para fases seguintes

- **Concorrência:** no máximo 3 jobs do Prism ao mesmo tempo, conforme a análise do cluster.
- **F2.2 (validador):**
  - INVALIDA_INFRA com sinais dentro da execução: K1, morte do model service;
  - janela de tempo de falhas da verificação de partida;
  - a verificação de saúde por execução não detectou a janela degradada em 5 das 6 execuções.
- **F2.3:** custo de ativação e de desativação como distribuições, incluindo a cauda da P11.
- **F2 (nova proposta):** medida da velocidade do cluster por execução (o pareamento no mesmo período já foi decidido em D8).
- **F4:**
  - A1.1 deve somar a reserva de 5% do kvcached (7,2 GB) à conta do controlador;
  - A1.2 resolve o impasse do T1;
  - A1.3 limita o ciclo de preempção da P1D0.
- **F6:** A3 (drenar ou preemptar) e A9 tratam a fome da folga de KV no `ovl_mix`.
- Antes da F4: separar o retrato de estado e a função de decisão em `simple_global.py` (pendência da F0).

## Como reproduzir

```bash
# submissão (um job por linha; <suite> em polyaxon/configs/)
PRISM_JOB_SUFFIX=-f1-loss-1 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_loss_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f1-freeze-3 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_freeze_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f1-repro-1 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f0_repro_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh
git worktree add --detach <wt> 2ac0098   # A/B de código: o braço antigo usa PRISM_PYTHON_SRC=<wt>/python
PRISM_JOB_SUFFIX=-f1-code-old-1 PRISM_PYTHON_SRC=<wt>/python PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_codeab_suite.tsv" polyaxon/submit.sh
# download: polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path <dl>/<job>
# F1.2: caminho de cada requisição não atendida
python3 polyaxon/trace_rids.py <dl>/f1-loss-1/outputs/tp_P1D0_a/ovl_trace_big/ts1
# F1.1: pilhas durante o travamento
python3 polyaxon/stack_summary.py <dl>/f1-freeze-3/outputs/n08_stacks/ovl_mem/rate0.2
# F1.7: tempo por etapa das desativações
grep -oE "Deactivate time cost: [0-9.]+s \([^)]*\)" <nível>/server_file.log
# F1.3 e F1.5: juntar, resumir, comparar (pandas: /mnt/scratch/scheduler/opt-env/bin/python)
PRISM_REPS=5 python3 polyaxon/collect_reps.py reports/data/F01/reproducao f1=<dl f1-repro>
python3 polyaxon/summarize_reps.py reports/data/F01/reproducao
python3 polyaxon/compare_reference.py reports/data/F01/reproducao/metricas.csv reports/data/F00/reproducao/metricas.csv \
  ovl_phases/rate0.5/A0.1_phases=ovl_phases/rate0.5/A0.1_phases ovl_phases/rate0.5/A0.2_phases=ovl_phases/rate0.5/A0.2_phases \
  ovl_trace_big/ts1/A0.3_trace12=ovl_trace_big/ts1/A0.3_trace12
python3 polyaxon/compare_reference.py reports/data/F01/ab_codigo/atual/metricas.csv reports/data/F01/ab_codigo/antigo/metricas.csv \
  ovl_phases/rate0.5/A0.1_phases=ovl_phases/rate0.5/A0.1_phases
python3 polyaxon/plot_suite.py reports/data/F01/travamento_execucoes reports/figs/F01/travamento
# P12: model service morto a 120 s, com e sem a correção (dois jobs juntos)
PRISM_JOB_SUFFIX=-f1-p12b-on PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_p12_on_suite.tsv" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f1-p12b-off PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_p12_off_suite.tsv" polyaxon/submit.sh
python3 -m unittest tests/robustness/test_model_service_alive.py
```
