# Prism sobre vLLM × Prism original (SGLang): análise crítica

Este documento compara o backend vLLM (`--engine-backend vllm`, branch `vllm-backend`) com o Prism
original sobre SGLang 0.3.4, com base em testes executados nas mesmas condições. O objetivo é ser
honesto sobre o que **não** funciona ou funciona pior. Cada afirmação de equivalência tem um teste que
a comprova, e cada diferença tem uma medição do seu impacto.

## Resumo

* **Funciona e é equivalente** em 1 GPU: API e formato de resposta, ativar/desativar (com saída idêntica
  após reativar), liberação de memória, preempção RETURN/RECOMPUTE, memória elástica (kvcached), resize,
  GPU scheduler e política do controller (mesmo número de ativações/remoções no `overload`).
* **Worker pool implementado (seção 1.1).** A primeira versão não tinha worker pool, e o exemplo completo
  do README em 2 GPUs (`prism2`) **travava 38% das requisições** (284/741). O worker pool vLLM recria o
  engine do modelo pedido dentro de um processo persistente por slot. Para isso foram necessárias
  alterações no vLLM, guardadas no repo como patches de runtime (`vllm_patches.py`). Com ele, o `prism2`
  completa **741/741**, com latência equivalente à do SGLang com worker pool (3 execuções de cada:
  TTFT médio 64–105 × 68–155 ms, TPOT 11–14 × 10–18 ms). A migração de modelo entre GPUs funciona e o
  `overload` completa 754/754 em todos os níveis. O SLO do `overload` varia muito entre execuções
  idênticas (vLLM a 10×: 44,7–82,4%; SGLang a 4×: 56–93%); na média o vLLM fica à frente em todos os
  níveis, mas as faixas se sobrepõem, exceto a 1× (seção 1.1).
* **Tensor parallelism (seção 1.8): o backend vLLM faz o que o original não faz.** O SGLang original
  recusa ativar modelos com TP > 1 e o worker pool dele só aceita TP = 1. No vLLM, TP = 2 passa em todos
  os testes de troca de modelo (com e sem worker pool), e o worker pool segue o desenho do artigo
  (slots TP sobre grupos de GPUs, processos TP reaproveitados): ativação até a primeira resposta em
  1,3–1,6 s, sem vazamento de memória. **O desempenho em TP é pior:** o vLLM 0.30 puro já é 30–45% mais
  lento por token que o SGLang 0.3.4 puro em TP = 2 eager, e com 2 modelos TP = 2 nas mesmas GPUs o
  Prism-vLLM satura em ~7,5 req/s contra 13,8 do Prism-SGLang.
* **Desempenho depende do regime e está confundido com a idade dos kernels.** Sob carga (2 modelos,
  8B + 3B, 20 req/s), o vLLM tem TPOT 36% menor (16,5 × 25,7 ms, 3 execuções). Em 5 req/s e no
  `prism1` (2× 3B, baixa carga) os dois empatam dentro da variação. A comparação mistura "arquitetura do
  backend" com "vLLM 0.30 (2026) × SGLang 0.3.4 (2024)" e não isola um do outro.
* **O adaptador tem custo próprio, menor que o do Prism original.** Contra `vllm serve` puro: ITL
  +2–10% e vazão −1 a −13% (pior com 32 requisições concorrentes). O Prism sobre SGLang, medido da
  mesma forma contra o SGLang puro, perde mais: ITL +15% e vazão −11 a −21% (seção 1.3).
* **Modo eager obrigatório:** o backend abre mão dos CUDA graphs, que no vLLM reduziriam o TPOT em 28%
  sob carga (15,6 → 11,3 ms).

## Metodologia

| | SGLang (original) | vLLM (esta branch) |
|---|---|---|
| Imagem | `gabrielliman/prism:sglang0.3.4-cu121` | `gabrielliman/prism:vllm0.30-kvcached0.1.6` |
| Engine | SGLang 0.3.4.post2 modificado pelo Prism (vLLM 0.6.3 para carregar pesos) | vLLM 0.30.0 atrás do adaptador; sem modificações no modo de um engine por modelo, com os patches de `vllm_patches.py` no worker pool |
| Atenção | FlashInfer 0.1.6 | FlashAttention 3 (escolha automática do vLLM) |
| Stack | torch 2.4, CUDA 12.1 | torch 2.13, CUDA 13.0 |
| kvcached | branch `prism/shm` (`--use-kvcached-v0`) | v0.1.6 (upstream) |

* Hardware: 1× ou 2× NVIDIA H200 (141 GB) no Polyaxon (`kunumi/hpc4ai`, fila `axia/default`).
* Mesmo código de plano de controle nos dois casos (esta branch). Os jobs do SGLang também servem como
  teste de regressão das mudanças no código compartilhado.
* As duas implementações rodam com `--disable-cuda-graph` (como no README), exceto no teste de CUDA graphs.
* **Repetições:** `cmp_overhead`, `cmp_sweep` e `prism1` foram executados 3 vezes por backend; `prism2` e
  `overload`, 3 vezes por backend (contando a primeira execução). As tabelas mostram média e
  [mín–máx]. As demais medições (paridade, ativação, CUDA graphs, TP) são de uma execução. A primeira
  versão deste documento tirava conclusões de execuções únicas; três delas não se sustentaram com as
  repetições e foram corrigidas: a vantagem do vLLM no `prism2`, a vantagem do SGLang no `prism1` e o
  +66% de TTFT do adaptador sob concorrência.
* Testes: `polyaxon/compare/` (`parity.py`, `activation.py`, `overhead.py`, `report.py`),
  `polyaxon/test_switching.py` e os passos de `polyaxon/run_examples.sh` (`cmp_parity`, `cmp_sweep`,
  `cmp_graph`, `cmp_overhead`, `switch_static`, `switch_elastic`, `static`, `elastic`, `prism1`,
  `prism2`, `overload`). A seção [Reprodução](#reprodução) traz os comandos.

## 1. Limitações

Em ordem de gravidade.

### 1.1 Worker pool e migração entre GPUs (era a limitação mais grave; resolvida)

**O problema (primeira versão, sem worker pool).** A política `simple-global` assume que qualquer modelo
pode ser ativado em qualquer GPU (semântica do worker pool). Sem pool, ela gera ações impossíveis e o
controller as repete sem desistir. No `prism2` (exemplo completo do README restrito às GPUs 0–1, 6
modelos, trace real, 741 requisições):

| configuração | concluídas | presas | causa |
|---|---|---|---|
| SGLang com worker pool (README) | 741 | 0 | — |
| SGLang sem worker pool | 719 | 22 | o controller pede `instance 1` de um modelo que só tem a instância 0 (defeito do Prism sem pool, independente do engine) |
| vLLM sem worker pool | 457 | **284** | o mesmo, mais a impossibilidade de mover o `model_4` para outra GPU |
| **vLLM com worker pool (atual)** | **741** | **0** | — |

**Como foi resolvido.** Um slot do worker pool (`VllmWorkerSlot` em `engine_adapter.py`) é um processo
persistente por (GPU, worker), como o `WorkerPoolModelRunner` do SGLang:
* Na ativação, o slot constrói um engine vLLM para o modelo pedido. Na desativação, destrói o engine e
  mantém o contexto CUDA e o grupo distribuído.
* Os pesos vêm de um cache em memória compartilhada da CPU (`/dev/shm`, `weight_cache.py`), uma cópia
  por modelo para todos os slots. É o equivalente a `--enable-cpu-share-memory` / model service.
* No RECOMPUTE, a requisição volta pelo Redis com o progresso, e qualquer slot que sirva o modelo
  depois, em qualquer GPU, continua a resposta.

Isso exigiu mexer no vLLM. As alterações estão em `vllm_patches.py`, aplicadas em runtime e verificadas
contra o vLLM 0.30.0:

| alteração no vLLM | por quê |
|---|---|
| load format `prism_shm` | carregar pesos já processados do cache compartilhado (8B em 0,28 s) |
| `teardown_engine` | `EngineCore.shutdown()` destrói o grupo distribuído; o slot libera o engine e mantém o processo |
| pular o profiling (ou reutilizar o resultado por modelo) | a medição se repetiria a cada ativação |
| cache do renderer por modelo | o renderer faz `deepcopy` do tokenizer (1,4–1,6 s) a cada engine |
| sem `gc.collect()` completo na montagem e uma só coleta no teardown | o vLLM chama `gc.collect()` ~10 vezes; com o heap inteiro do processo são ~1,5–2 s |
| pular o warmup de kernels a partir do 2º engine do processo | os kernels já estão carregados; a primeira geração não piora (0,70 s com e sem) |

**Medições** (`polyaxon/experiments/engine_swap.py`, um processo alternando Llama-3.2-3B e
Llama-3.1-8B; 2 rodadas em regime, H200):

| | montar engine 3B / 8B | saída igual à carga do disco | memória após desmontar |
|---|---|---|---|
| vLLM sem alterações (pesos do cache) | 4,42 / 4,64 s (estático), 5,24 / 5,36 s (elástico) | sim | sem deriva (0,03 GB) |
| com as alterações | **0,23 / 0,40 s** (estático), **0,52 / 0,57 s** (elástico) | **sim, em todos os ciclos** | sem deriva (0,03 GB) |

O teste funcional (`polyaxon/test_worker_pool.py`, 2 GPUs) passa em todas as verificações:
* ativar num slot livre um modelo que nunca esteve ativo;
* desativar libera a memória do slot;
* reativar dá a mesma saída;
* RECOMPUTE entre slots completa os 400 tokens;
* migrar o modelo da GPU 0 para a GPU 1: 0,85–0,95 s até a primeira resposta.

**O que ainda é diferente ou pior:**
* **Primeira ativação de cada slot:** o primeiro engine de um processo paga a inicialização de CUDA/NCCL
  e a compilação JIT de kernels (~7 s). Por isso o slot se aquece na partida (monta e desmonta o menor
  modelo), o que aumenta o tempo de subida do servidor (`prism2`: 125 s; SGLang: 70 s).
* **Desativação** (desmontar o engine): 0,42–0,46 s no modo estático e 0,68–0,76 s no elástico (o kvcached leva ~0,13 s), contra ~0,35–0,40 s do SGLang. O tempo restante é praticamente todo a coleta de lixo completa (~0,4–0,6 s), necessária para liberar o engine anterior; a primeira versão do teardown levava ~1,1 s porque o próprio vLLM fazia uma segunda coleta.
* **Sob carga extrema,** montar engines compete com a inferência das outras instâncias na mesma GPU:
  houve ativações de até 5,5 s no `overload` 10×.

`overload` (8 modelos numa GPU, 4 desligados no início), SLO (TTFT e TPOT), média [mín–máx] de 3
execuções com worker pool nos dois backends:

| velocidade | vLLM worker pool | SGLang worker pool | vLLM sem pool (1 execução) |
|---|---|---|---|
| 1× | 94,8% [92,8–98,3] | 88,1% [87,0–88,7] | 95,4% |
| 2× | 92,6% [86,1–97,9] | 80,1% [65,6–96,7] | 89,0% |
| 4× | 89,7% [81,4–95,4] | 80,2% [56,0–93,4] | 97,3% |
| 10× | 69,8% [44,7–82,4] | 53,8% [35,5–74,5] | 91,8% |

Em todos os casos foram 754/754 concluídas, sem abortadas, e o controller fez as mesmas ativações e
remoções (5/4 até 4×; 4/2 ou 4/3 a 10×). **A variância entre execuções idênticas é maior que a
diferença entre os backends**, exceto a 1×, onde a faixa do vLLM fica inteira acima da do SGLang. Uma
execução isolada do `overload` não serve para comparar backends. No modo sem pool, ativar só recopia os
pesos num engine que continua montado; no worker pool, cada troca monta e desmonta um engine, e sob
carga 10× isso pesa (a execução sem pool não foi repetida).

**Um ajuste necessário no caminho:** os modelos ativados na partida recebiam KV sem limite, porque no
worker pool não havia a config por modelo, e sob carga deixavam os modelos ativados depois sem espaço.
Agora cada modelo recebe o `max_memory_pool_size` da sua config. Isso subiu o SLO a 10× de 67,2% para
82,4%.

### 1.2 Modo eager obrigatório (sem CUDA graphs)

Ativar copia os pesos para endereços de GPU novos, o que invalidaria graphs capturados. Por isso o
adaptador força `enforce_eager`. O teste `cmp_graph` usa um modo só de medição
(`PRISM_VLLM_CUDA_GRAPH=1`, que recusa ativar/desativar).

| 2 modelos, 20 req/s | eager (o que o backend usa) | com CUDA graphs | impacto |
|---|---|---|---|
| vLLM TPOT médio | 15,6 ms | 11,3 ms | −28% |
| vLLM E2E médio | 6,03 s | 4,37 s | −28% |
| SGLang TPOT médio | 25,0 ms | 22,3 ms | −11% |

O README do Prism também desliga os graphs, então a comparação "como publicado" é justa. Ainda assim, o
vLLM deixa de ganhar 28% de TPOT. Uma alternativa seria usar o sleep mode do vLLM (CuMemAllocator), que
preserva endereços, mas a combinação com o kvcached não foi testada.

### 1.3 Overhead do próprio adaptador

**Teste:** `cmp_overhead`, Llama-3.2-3B atrás do Prism × o engine puro com as mesmas configurações
(eager, sem prefix cache, 20 GB de KV): `vllm serve` para o backend vLLM e o SGLang 0.3.4.post2
original (sem as modificações do Prism) para o backend SGLang. 256 tokens de saída, mediana por
requisição, média [mín–máx] de 3 execuções.

| concorrência | | ITL Prism / puro | tok/s Prism / puro | TTFT Prism / puro |
|---|---|---|---|---|
| 1 | vLLM | 11,2 / 10,8 ms (+4%) | 89 / 92 (−4%) | 16 / 26 ms |
| 1 | SGLang | 7,8 / 6,8 ms (+15%) | 127 / 147 (−14%) | 14 / 11 ms |
| 8 | vLLM | 11,5 / 11,1 ms (+4%) | 687 / 711 (−3%) | 37 / 41 ms |
| 8 | SGLang | 8,2 / 7,2 ms (+14%) | 967 / 1089 (−11%) | 36 / 30 ms |
| 32 | vLLM | 12,7 / 11,6 ms (+10%) | 2394 [2323–2450] / 2696 (−11%) | 88 [78–95] / 93 [85–105] ms |
| 32 | SGLang | 8,4 / 7,2 ms (+17%) | 3336 [3206–3585] / 4206 (−21%) | 102 / 90 ms |

**Leitura crítica:**
* O adaptador vLLM custa menos que as modificações do próprio Prism no SGLang. Portanto o custo
  restante do backend vLLM não é uma regressão em relação ao original.
* O "+66% de TTFT com 32 concorrentes" da primeira versão deste documento era ruído de uma execução: nas
  repetições, o TTFT do Prism-vLLM fica dentro da faixa do `vllm serve`.
* O SGLang 0.3.4 puro decodifica o 3B mais rápido que o vLLM 0.30 puro em eager (ITL 7,2 × 11,6 ms).
  Sob a carga mista do `cmp_sweep` (8B + 3B) a relação se inverte (3.1).
* Causas prováveis do custo do adaptador (não perfiladas): o loop Python inspeciona o scheduler do vLLM
  a cada step, a saída passa por ZMQ e pelo request handler, e as requisições entram pelo Redis em lotes
  (`free_tokens / avg_input_len`).
* O TTFT menor com concorrência 1 no vLLM vem do caminho OpenAI do `vllm serve`, mais pesado que o
  `/generate`.

### 1.4 Memória e inicialização

| | SGLang | vLLM | diferença |
|---|---|---|---|
| GPU retida por engine desativado (`activation.py`) | 0,72 GB | 0,88 GB | +22% |
| Subida com 8 modelos (`overload`) | 60–80 s (worker pool) | 130–165 s (sem pool), 105–160 s (worker pool) | ~2× |
| Subida com 6 modelos em 2 GPUs (`prism2`) | 70 s | 105 s (sem pool), 125 s (worker pool) | +50–80% |
| Pesos na CPU | uma cópia compartilhada por modelo (`--enable-cpu-share-memory`) | sem pool: uma cópia pinned **por engine**; worker pool: uma cópia por modelo em `/dev/shm` | igual com worker pool |

A subida mais lenta tem três causas:
* Os engines na mesma GPU sobem um de cada vez, por um lock no adaptador, porque o vLLM mede a memória
  livre da GPU inteira.
* Sem pool, cada engine carrega pesos do disco.
* No worker pool, o cache de pesos é preenchido na partida (~60 s para 8B + 3B, carregando do disco) e
  cada slot se aquece montando um engine.

### 1.5 Semântica: diferenças e pontos não verificados

* **RETURN** tem a mesma semântica pelo código (`Scheduler._complete_ongoing_requests` monta o batch da
  fila mas não executa o forward): nos dois, requisições na fila terminam com 0 tokens e
  `finish_reason=length`. **Não medido** para requisições na fila; o teste só cobre a requisição em
  execução.
* **Resize de memória no modo estático** é ignorado (o vLLM fixa o número de blocos na partida). O
  SGLang lança erro nesse caso, então ambos efetivamente não suportam, só que de formas diferentes.
* **`BatchRunReq`/`BatchRetractDecodeReq`** são inferidos a cada step a partir do estado do scheduler do
  vLLM, não emitidos no momento da decisão. A informação que o controller recebe é aproximada.
* **`update_weights`, LoRA, overlap schedule, data parallelism, multi-nó e async loading** não são
  suportados (rejeitados na partida). Model service e `--enable-cpu-share-memory` são aceitos e
  atendidos pelo cache de pesos do worker pool.

### 1.6 Não testado

* **Modelos grandes de verdade com TP > 1** (70B em TP = 4/8, como no artigo), TP > 2 e TP em mais de
  um grupo de GPUs ao mesmo tempo. Os testes de TP usam Llama-3.1-8B e 3B em TP = 2 (seção 1.8).
* TP no `overload` e no `prism2` (o trace do README só tem modelos TP = 1).
* Modelos MLA, híbridos, quantizados e multimodais.
* Saída estruturada além de regex simples. `json_schema` não foi testado.

### 1.7 Fragilidade de manutenção

O adaptador lê internals do vLLM (`engine_core.scheduler.requests`, `block_pool`,
`model_runner.kv_caches`, parâmetros do modelo) e do kvcached (`pool_registry`, `page_size`), e depende
do autopatch do kvcached ser aplicado no import. Isso funciona com o par vLLM 0.30 + kvcached 0.1.6
fixado na imagem, mas **qualquer upgrade precisa repetir esta bateria**.

O worker pool aumenta essa dependência. `vllm_patches.py` substitui funções internas do vLLM: o
`determine_available_memory` e o `compile_or_warm_up_model` do `Worker` e o `renderer_from_config`, além de desligar o `gc.collect`
durante a montagem e o shutdown. Também reconstrói o shutdown do `EngineCore`. O módulo
avisa quando a versão do vLLM não é a 0.30.0, mas não consegue detectar mudanças de comportamento. É
para isso que servem `swap_*`, `wp_test` e `switch_*`.

Durante a validação também apareceram dois defeitos de integração, ambos já corrigidos:
* o nome do segmento do kvcached era fixado antes de o adaptador configurá-lo, o que quebrava o GPU scheduler;
* eu introduzi uma regressão no caminho SGLang com worker pool: as classes de modelo do SGLang deixaram de
  ser registradas no processo principal. Os jobs de comparação a detectaram. Isso mostra que o código
  compartilhado precisa de testes nos dois backends.

### 1.8 Tensor parallelism (TP > 1)

**Ponto de partida.** No Prism original, TP > 1 só existe com o modelo sempre ativo: o
`handle_activate_request` do SGLang lança "Activating a model with tp > 1 is not supported yet.", o
worker pool aceita apenas TP = 1 e a política global supõe uma GPU por modelo ativo. O job `399e778b`
confirmou: o SGLang serve dois modelos TP = 2, mas o teste de troca derruba o servidor na ativação.

**O que foi implementado no backend vLLM** (seguindo o artigo, §7 e apêndice A.2.2):
* Sem worker pool: um engine vLLM TP por modelo (`MultiprocExecutor`, um processo por rank), com
  ativar/desativar via `collective_rpc` em todos os ranks.
* Com worker pool: além dos slots TP = 1 por GPU, slots TP sobre grupos de GPUs (`--tp-workers-per-group`).
  Cada slot TP é tratado pelo GPU scheduler da primeira GPU do grupo, e a política coloca o modelo num
  grupo em que todas as GPUs comportam a parte do modelo daquele rank. Um executor persistente
  (`persistent_executor.py`) mantém os processos dos ranks e o grupo NCCL entre engines (os "contextos
  distribuídos reutilizáveis" do artigo); o cache de pesos em `/dev/shm` guarda um shard por rank.
* A migração automática de modelos TP entre grupos não foi implementada (a política só migra modelos TP = 1).

**Defeitos encontrados no caminho (todos corrigidos):**
* **Travamento intermitente na subida de engines TP**, com um ou dois engines nas GPUs (`tp_sweep`,
  `tp_overhead`). O vLLM 0.30 tenta primeiro all-reduces que usam multicast NVLink (FlashInfer `mnnvl` e
  memória simétrica do torch), e o multicast falha às vezes no rank 1 ("init_multicast_for_block"). Os
  engines TP agora sobem sem esses caminhos (`TP_ALLREDUCE_ENV` em `vllm_patches.py`): o vLLM usa o custom
  all-reduce (CUDA IPC) e o NCCL. Desligar esses caminhos não reduziu o desempenho (7,5 × 6,5 req/s antes).
* Os patches de runtime não existiam nos processos dos ranks (criados com `spawn`); agora são aplicados
  quando o rank importa a worker extension.
* **Vazamento de memória ao reaproveitar ranks:** se o warmup de kernels do vLLM roda num rank
  reaproveitado, os pesos do modelo anterior ficam na GPU (+3 GB por rank para o 3B e +7,5 GB para o 8B,
  a cada troca). Com o warmup pulado, como o worker pool faz, a memória fica constante. As flags
  `PRISM_VLLM_*` agora são repassadas aos ranks a cada reconstrução. A causa dentro do vLLM não foi
  identificada.

**Testes de equivalência** (2× H200):

| teste | resultado |
|---|---|
| `tp_switch_static` / `tp_switch_elastic` (`test_switching.py`, 8B + 3B em TP = 2, sem pool) | todas as verificações passam: saída idêntica após reativar, RETURN, RECOMPUTE (400 tokens), resize, ativação dimensionada; ativar 0,07–0,18 s; desativar 0,05 s (a primeira, 2,5–3,8 s, cria a cópia dos pesos na CPU) |
| `wp_tp_test` (`test_worker_pool_tp.py`: 8B em TP = 2 no pool + dois 3B em TP = 1) | todas passam: ativação pelo pool até a primeira resposta em 1,26 s (reativação 1,60 s); as duas GPUs recebem a sua parte; desativar libera as duas em 0,26 s; saída idêntica após reativar; RECOMPUTE completa; modelos TP = 1 não são afetados; após 3 ciclos a memória volta exatamente ao início |
| `swap_elastic` com `PRISM_SWAP_TP=2` (troca 3B ↔ 8B no mesmo par de ranks) | montar engine: 0,6–0,8 s com os patches (2,5–4,7 s sem); desmontar: 0,57–0,79 s; saída idêntica em todos os 18 ciclos |

O artigo cita 1,5 s para ativar um 70B em TP = 4/8; aqui o modelo é bem menor, então os números não são
comparáveis diretamente.

**Desempenho** (`tp_overhead`: um 8B em TP = 2 atrás do Prism × o engine puro, 2 execuções por backend;
mediana por requisição, médias das execuções):

| concorrência | ITL Prism / puro, vLLM | ITL Prism / puro, SGLang | vazão Prism × puro, vLLM | vazão Prism × puro, SGLang |
|---|---|---|---|---|
| 1 | 16,9 / 14,9 ms | 11,4 / 10,3 ms | 59 / 67 tok/s (−12%) | 85 / 97 (−12%) |
| 8 | 17,6 / 15,4 ms | 12,3 / 11,0 ms | 453 / 516 (−12%) | 647 / 718 (−10%) |
| 32 | 17,9 / 15,3 ms | 12,9 / 11,8 ms | 1719 / 2051 (−16%) | 2401 / 2635 (−9%) |

`tp_sweep`: 8B + 3B, ambos em TP = 2 nas GPUs 0–1, trace sintético; vLLM 3 execuções, SGLang 2:

| taxa | req/s vLLM / SGLang | TTFT médio vLLM / SGLang | TPOT médio vLLM / SGLang |
|---|---|---|---|
| 5 | 2,38 [2,19–2,65] / 2,69 | 0,24 s / 0,16 s | 102 / 111 ms |
| 10 | 5,08 [4,92–5,20] / 6,34 | **23,4 s** / 0,13 s | 88 / 91 ms |
| 20 | 7,48 [6,48–8,03] / 13,79 | **50,5 s** / 1,3 s | 68 / 84 ms |

**Leitura crítica:**
* O custo do adaptador em TP = 2 (−12 a −16% de vazão) é parecido com o das modificações do Prism no
  SGLang (−9 a −12%). **A diferença vem principalmente do vLLM:** o `vllm serve` puro em TP = 2 eager
  tem ITL de 15 ms contra 10–11 ms do SGLang puro. Em eager, cada camada lança kernels e sincroniza o all-reduce a partir do Python; os CUDA
  graphs, que o backend não pode usar (1.2), seriam justamente o remédio.
* Com dois engines TP nas mesmas GPUs, o TPOT dos dois backends vai a 90–110 ms já em 5 req/s (contra
  15–18 ms com um engine sozinho): os all-reduces de um engine esperam enquanto o outro ocupa as GPUs. Isso
  vale para os dois backends e pesa para qualquer colocação de modelos TP no mesmo grupo.
* O vLLM satura antes: a 10 e 20 req/s as requisições se acumulam na fila (TTFT de dezenas de segundos)
  enquanto o TPOT até cai. A lógica de admissão do adaptador é a mesma do TP = 1, onde o vLLM não satura,
  então a explicação mais provável é a menor capacidade do vLLM eager em TP = 2, ampliada pela
  disputa entre os dois engines. **Não foi isolado:** o teste com dois `vllm serve` puros dividindo as
  GPUs, que separaria o efeito do vLLM do efeito do adaptador sob colocação, não foi feito.

## 2. O que está equivalente, e os testes que comprovam

### 2.1 API e formato de resposta

**Teste:** `parity.py`, com 160 requisições por backend (2 modelos × 8 prompts × 10 combinações de parâmetros).

| verificação | SGLang | vLLM |
|---|---|---|
| Requisições bem-sucedidas | 160/160 | 160/160 |
| Chaves de `meta_info` (timestamps usados pelo benchmark etc.) | idênticas | idênticas |
| Distribuição de `finish_reason` por caso | igual em todos os 10 casos | |
| `one_token`, `stop_str`: texto idêntico | 16/16, 16/16 | |
| `regex` `[0-9]{1,6}`: saída casa o regex | 16/16 | 16/16 |
| Mesmo nº de tokens (exceto `min_tokens` e `regex`) | 16/16 em todos os casos | |

### 2.2 Ativar/desativar

**Teste:** `activation.py`, 10 ciclos por modelo, servidor estático (8B + 3B, pools de 20 GB).

| | SGLang (mediana) | vLLM (mediana) |
|---|---|---|
| Desativar 8B / 3B | 0,40 / 0,33 s | 0,17 / 0,04 s |
| Ativar 8B / 3B | 0,41 / 0,25 s | 0,30 / 0,13 s |
| Pior ativação 8B / 3B | 0,78 / 1,10 s | 1,46 / 0,89 s |
| GPU liberada 8B / 3B (pesos + pool de KV) | 35,4 / 26,5 GB | 35,0 / 26,0 GB |
| Saída greedy idêntica após cada reativação | 20/20 | 20/20 |

Os dois cumprem a meta do Prism (ativação < 1,5 s). Na mediana o vLLM é mais rápido, mas **varia mais**:
no 8B, os ciclos 5–8 levaram 0,53 / 0,79 / 1,46 / 0,64 s, contra 0,30 s nos demais (o SGLang ficou entre
0,39 e 0,78 s). A causa não foi investigada; a cópia pinned → GPU concorre com a outra instância na
mesma GPU.

### 2.3 Troca de modelos com tráfego

**Teste:** `test_switching.py` (estático e elástico, 2× Llama-3.1-8B).

* 64 requisições em andamento: desativar com `preempt=False` termina todas e libera pesos + KV (vLLM:
  37,0 → 18,4 GB no modo elástico, com sobra de 64 MB = uma página por camada).
* Ativação com saída greedy idêntica, recusa de ativação duplicada, RETURN (texto é prefixo da saída
  completa), RECOMPUTE (completa os 400 tokens e mantém exatamente o texto já transmitido), resize e
  ativação com `memory_pool_size`: **todos PASS nos dois backends**.
* A única verificação em que diferem é "KV reportado como liberado", que **falha no SGLang**: após
  desativar, o SGLang continua reportando `memory_pool_memory` = tamanho configurado (10 GB) embora a
  memória tenha sido liberada. O vLLM reporta 0. Isso é um defeito de contabilidade do original.

### 2.4 RECOMPUTE

Nos dois backends, o texto depois da retomada pode divergir de uma execução sem interrupção. O KV
recalculado num único prefill não é bit a bit igual ao construído no decode, e o greedy acaba escolhendo
outro token. Divergência no caractere: SGLang 893 (elástico), vLLM 997. No estático, o SGLang não
divergiu nesta execução. É uma propriedade compartilhada e não uma regressão.

### 2.5 Plano de controle em 1 GPU

**Teste:** `overload`, com 8 modelos numa GPU (4 começam desligados), trace real em 1×/2×/4×/10×, com a
configuração completa do README (worker pool, model service) nos dois backends, 3 execuções cada (tabela
na seção 1.1). Os 12 níveis de cada backend (3 execuções × 4 velocidades) concluíram 754/754 sem
abortadas, e o controller tomou as mesmas decisões nos dois (5 ativações / 4 remoções até 4×). Isso
indica que o GPU scheduler e a política funcionam com o adaptador. O SLO médio melhor do vLLM não deve
ser atribuído ao adaptador (ver 3.1), e as faixas se sobrepõem.

Também equivalentes, com worker pool nos dois e 3 execuções:

| | concluídas | TTFT médio | TPOT médio | P99 TTFT |
|---|---|---|---|---|
| `prism1` SGLang (2× 3B, 1 GPU) | 318/318 | 104 [82–130] ms | 14,8 [13,6–16,8] ms | 1,9 [1,2–3,0] s |
| `prism1` vLLM | 318/318 | 125 [94–151] ms | 13,3 [13,1–13,5] ms | 2,8 [2,2–3,8] s |
| `prism2` SGLang (6 modelos, 2 GPUs) | 741/741 | 99 [68–155] ms | 13,3 [9,9–17,6] ms | 0,9 [0,7–1,2] s* |
| `prism2` vLLM | 741/741 | 76 [60–105] ms | 12,2 [11,3–13,8] ms | 1,3 [0,5–2,0] s* |

\* P99 das duas repetições; a primeira execução não o registrou nesta tabela.

Os exemplos `static` e `elastic` do README (145 requisições por modelo, 0 abortadas) também passam nos
dois (1 execução).

## 3. O que é diferente, e o impacto medido

### 3.1 Desempenho

**Teste:** `cmp_sweep` (8B + 3B sempre ativos, trace sintético de 60 s, eager nos dois), média
[mín–máx] de 3 execuções.

| taxa | backend | req/s | TTFT médio | TPOT médio | E2E médio |
|---|---|---|---|---|---|
| 5 | SGLang | 4,24 | 29,6 [29,3–29,8] ms | 14,0 [14,0–14,1] ms | 5,42 s |
| 5 | vLLM | 4,21 | 29,8 [27,7–32,4] ms | 14,2 [13,9–14,4] ms | 5,46 s |
| 10 | SGLang | 9,23 | 67,4 [43,3–96,5] ms | 17,6 [17,2–18,1] ms | 6,80 s |
| 10 | vLLM | 9,18 | 26,5 [25,8–27,6] ms | 13,8 [13,5–14,0] ms | 5,32 s |
| 20 | SGLang | 17,86 | 51,2 [43,8–62,3] ms | 25,7 [24,8–26,6] ms | 9,89 s |
| 20 | vLLM | 18,23 | 33,2 [30,3–37,5] ms | 16,5 [15,8–17,4] ms | 6,37 s |

Exemplos do README (1 execução): `static` (2× 8B, 10 req/s) com TPOT 24,9 × 16,9 ms; `elastic` com
25,7 × 18,7 ms. O `prism1` empata (seção 2.5); a primeira versão deste documento comparava o SGLang com
worker pool a um vLLM sem pool numa execução só e concluía o contrário.

**Interpretação crítica:**
* A vazão é a mesma em todos os casos: a carga não satura nenhum dos dois.
* Em 5 req/s os dois empatam. A partir de 10 req/s o vLLM 0.30 decodifica bem mais rápido, com faixas
  que não se sobrepõem, o que é coerente com kernels mais novos (FlashAttention 3 no H200 × FlashInfer
  0.1.6).
* Com um só modelo de 3B e batch pequeno (1.3), o SGLang 0.3.4 puro é mais rápido por token que o vLLM
  0.30 puro em eager; o ganho do vLLM aparece com batches maiores e o modelo de 8B.
* **Nada disso mede o design do backend**, e sim duas gerações de engine. Para uma conclusão sobre o
  design seria preciso comparar com um SGLang recente portado da mesma forma, o que não foi feito.

### 3.2 Saídas numericamente diferentes

| caso | texto idêntico entre backends | prefixo comum médio |
|---|---|---|
| 1 token, stop string | 16/16 | 100% |
| greedy 64 tokens | 10/16 | 82% |
| greedy 256 tokens | 5/16 | 56% |

A divergência cresce com o comprimento e é zero em respostas curtas. Isso é o padrão de diferenças de
arredondamento em bf16 entre kernels, não de erro de mapeamento. Outros indícios apontam no mesmo
sentido: mesmos `finish_reason` e mesmo número de tokens em todos os casos comparáveis. **Impacto:**
resultados de qualidade (ex.: avaliação de respostas) não são reproduzíveis entre backends token a
token.

### 3.3 Diferenças de semântica de sampling

* **`min_new_tokens` com stop string:** o SGLang 0.3.4 **ignora** o mínimo quando a parada é por stop
  string (`check_finished` só aplica o mínimo a EOS/stop token ids). Ele parou com 2–28 tokens com
  mínimo de 32 (0/16 respeitaram), e o vLLM respeitou em 16/16. O vLLM está correto, mas o
  comportamento difere do original.
* **`no_stop_trim`:** o SGLang mantém o token inteiro que contém o stop (ex.: `".\n\n"`), e o vLLM corta
  logo após o stop string (3/16 respostas diferentes).

### 3.4 Contabilidade de memória para o GPU scheduler

O vLLM reporta `req_to_token_pool_memory = 0`, porque mantém as tabelas de blocos no scheduler e não num
pool na GPU. O SGLang reserva e reporta 1,0 GB por modelo nesse pool (medido em `test_switching`). O
`ResourceManager` calcula o orçamento de KV como `memória utilizável − pesos − req_to_token`. Com o vLLM,
esse orçamento fica ~1 GB maior por modelo ativo, sem que exista a memória correspondente: os buffers
internos do vLLM não são contabilizados. A admissão fica mais otimista. O impacto não foi isolado; no
`overload` as decisões foram as mesmas.

## 4. Recomendações

1. **Em multi-GPU, usar o backend vLLM com `--enable-worker-pool`** (seção 1.1). Sem pool, a política
   `simple-global` gera ações impossíveis. Convém corrigir o loop de `instance 1` do controller, que
   afeta os dois backends no modo sem pool.
2. **A cada upgrade do vLLM**, rodar `swap_static`/`swap_elastic`, `wp_test` e `switch_*` antes de usar:
   os patches de `vllm_patches.py` dependem de internals do vLLM 0.30.
3. Antes de publicar números comparativos, **repetir as medições** (≥ 3 execuções; o `overload` precisa de
   mais, dada a variância), separar o efeito do engine com um SGLang recente e perfilar o adaptador (1.3).
4. Avaliar o sleep mode do vLLM para recuperar os CUDA graphs (−28% TPOT), testando a convivência com o
   kvcached.
5. Antes de usar TP com modelos grandes, repetir `tp_switch_*`, `wp_tp_test` e `swap_*` com
   `PRISM_SWAP_TP` no tamanho real (TP = 4/8) e medir a colocação de engines TP no mesmo grupo de GPUs, que
   custa caro nos dois backends (1.8).

## Reprodução

```bash
# Comparação completa (1 GPU): mesmos passos com cada backend
STEPS="cmp_parity cmp_sweep cmp_graph switch_static switch_elastic static elastic prism1"
PRISM_IMAGE=gabrielliman/prism:sglang0.3.4-cu121 PRISM_JOB_ENV="PRISM_BACKEND=sglang PRISM_STEPS='$STEPS' PRISM_TIMEOUT=9000" polyaxon/submit.sh
PRISM_IMAGE=gabrielliman/prism:vllm0.30-kvcached0.1.6 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS='$STEPS cmp_overhead' PRISM_TIMEOUT=9000" polyaxon/submit.sh
# overload (1 GPU) e prism2 (2 GPUs): flags do README, com worker pool nos dois backends;
# PRISM_NO_WORKER_POOL=1 remove o worker pool (para comparar)
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS=prism2 PRISM_TIMEOUT=5400" PRISM_IMAGE=... polyaxon/submit.sh
# worker pool vLLM: troca de engine num processo (1 GPU) e teste funcional com migração (2 GPUs)
PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS='swap_static swap_elastic'" PRISM_IMAGE=... polyaxon/submit.sh
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_WP_GPUS=2 PRISM_STEPS=wp_test" PRISM_IMAGE=... polyaxon/submit.sh
# TP = 2 (2 GPUs): troca de modelos sem pool, worker pool com modelo TP, troca de engine TP, desempenho
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS=tp_switch_static,tp_switch_elastic,wp_tp_test" PRISM_IMAGE=... polyaxon/submit.sh
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_SWAP_TP=2 PRISM_STEPS=swap_elastic" PRISM_IMAGE=... polyaxon/submit.sh
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=sglang PRISM_STEPS=tp_overhead,tp_sweep" polyaxon/submit.sh   # e o mesmo com vllm
# Tabelas a partir dos outputs baixados (polyaxon ops artifacts -d outputs)
python3 polyaxon/compare/report.py <outputs SGLang> <outputs vLLM>
python3 polyaxon/analyze_overload.py <outputs>
```

Execuções usadas neste documento (Polyaxon `kunumi/hpc4ai`):
* SGLang: `4fcd2f95` (bateria), `235bc00b` (`prism1`), `9b084c94` (`overload`), `b5eb5501` (`prism2`),
  `211d4f8e` (`prism2` sem worker pool);
* vLLM sem pool: `27b57700` (bateria), `f73352ca` (overhead), `2bf77793` (`overload`), `d3a8ff52`
  (`prism2`, interrompido após 64 min travado);
* vLLM worker pool: `21fa2230` (troca de engine), `bf99955f` (`prism2`), `c5a5f59b` (`overload`),
  `f6d0ea37` (`wp_test` + teardown);
* repetições (`cmp_overhead` + `cmp_sweep` + `prism1`; `prism2`; `overload`): vLLM `e3048b9c`, `9bd56f7f`,
  `24caea12`, `715a75be`, `c8d4c95f`, `bfec63c4`, `5469b118`; SGLang `beb61ac5`, `b77b5e20`, `469291e0`,
  `22991cd9`, `6e5f3494`, `739a924e`, `7bcb6dc0`;
* TP: SGLang `399e778b` (`tp_sweep` + troca, que falha), `476fd7a6` e `e3c082d6` (`tp_overhead` +
  `tp_sweep`); vLLM `b2604e77` e `f6b62262` (`tp_switch_*`), `7523e3a6`, `b9c788d9` e `f68a3fcc`
  (`tp_sweep`; os dois últimos também `tp_overhead`), `e4db17a6` (`wp_tp_test` e `swap_*` em TP = 2).
