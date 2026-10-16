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
  completa **741/741** (TTFT 64 × 155 ms e TPOT 11,3 × 17,6 ms do SGLang com worker pool), a migração de
  modelo entre GPUs funciona e o `overload` completa 754/754 em todos os níveis. Restam diferenças:
  montar e desmontar um engine custa mais que a troca de pesos do modo sem pool, e sob carga 10× o SLO
  do worker pool vLLM (82,4%) fica abaixo do vLLM sem pool (91,8%), embora acima do SGLang (74,5%).
* **Desempenho depende do regime e está confundido com a idade dos kernels.** Sob carga (2 modelos,
  8B + 3B, 20 req/s), o vLLM tem TPOT 38% menor (15,6 × 25,0 ms). Em carga baixa com modelos pequenos
  (`prism1`), o SGLang é melhor (TPOT 8,7 × 13,5 ms; TTFT 34,5 × 61,3 ms). A comparação mistura
  "arquitetura do backend" com "vLLM 0.30 (2026) × SGLang 0.3.4 (2024)" e não isola um do outro.
* **O adaptador tem custo próprio**, medido contra `vllm serve` puro: +11% de ITL, −9 a −15% de vazão e
  +66% de TTFT com 32 requisições concorrentes.
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
* **Ressalva:** cada medição foi executada uma vez. Não há repetições, então a variância é
  desconhecida. Há sinais de ruído: no `overload` do SGLang, o nível 2× teve SLO pior que o 4×. As diferenças
  de poucos por cento devem ser tratadas como empates.
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

`overload` (8 modelos numa GPU, 4 desligados no início), SLO (TTFT e TPOT):

| velocidade | vLLM worker pool | SGLang worker pool | vLLM sem pool |
|---|---|---|---|
| 1× | 98,3% | 88,7% | 95,4% |
| 2× | 97,9% | 78,1% | 89,0% |
| 4× | 95,4% | 91,1% | 97,3% |
| 10× | 82,4% | 74,5% | 91,8% |

Em todos os casos foram 754/754 concluídas, sem abortadas, e o controller fez as mesmas ativações e
remoções. No modo sem pool, ativar só recopia os pesos num engine que continua montado. No worker pool,
cada troca monta e desmonta um engine, e sob carga 10× isso pesa.

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

**Teste:** `cmp_overhead`, Llama-3.2-3B no Prism-vLLM × `vllm serve` puro com as mesmas configurações
(eager, sem prefix cache, 20 GB de KV); 256 tokens de saída; mediana por requisição.

| concorrência | ITL Prism / puro | tok/s Prism / puro | TTFT Prism / puro |
|---|---|---|---|
| 1 | 12,5 / 11,2 ms (+12%) | 80 / 87 (−9%) | 19 / 32 ms |
| 8 | 12,6 / 11,3 ms (+12%) | 599 / 703 (−15%) | 40 / 41 ms |
| 32 | 13,1 / 11,8 ms (+11%) | 2321 / 2642 (−12%) | **110 / 67 ms (+66%)** |

**Causas prováveis (não perfiladas):**
* o loop Python do adaptador inspeciona o scheduler do vLLM a cada step;
* a saída passa por ZMQ e pelo request handler;
* as requisições entram pelo Redis com a fórmula de vazão do Prism (`free_tokens / avg_input_len`), que
  admite em lotes e atrasa o TTFT sob concorrência.

O TTFT menor com concorrência 1 vem do caminho OpenAI do `vllm serve`, mais pesado que o `/generate`.

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
  atendidos pelo cache de pesos do worker pool. O worker pool vLLM aceita apenas TP = 1.

### 1.6 Não testado

* **Tensor parallelism (TP > 1):** o código existe (o adaptador usa `collective_rpc` em todos os ranks),
  mas nunca foi executado. Os testes multi-GPU acima são de modelos TP=1 em GPUs diferentes.
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

**Teste:** `overload`, com 8 modelos numa GPU (4 começam desligados), trace real em 1×/2×/4×/10×. O SGLang usa a
configuração completa do README (worker pool, model service); o vLLM usa engines por modelo.

| velocidade | concluídas (SG / vLLM) | ativações/remoções (SG / vLLM) | SLO SG | SLO vLLM |
|---|---|---|---|---|
| 1× | 754 / 754 | 5/4 / 5/4 | 88,7% | 95,4% |
| 2× | 754 / 754 | 5/4 / 5/4 | 78,1% | 89,0% |
| 4× | 754 / 754 | 5/4 / 5/4 | 91,1% | 97,3% |
| 10× | 754 / 754 | 4/3 / 4/2 | 74,5% | 91,8% |

O controller toma praticamente as mesmas decisões nos dois backends, o que indica que o GPU scheduler e a política
funcionam com o adaptador. O SLO melhor do vLLM não deve ser atribuído ao adaptador (ver 3.1).

Também equivalentes: `prism1` (318/318 nos dois) e os exemplos `static` e `elastic` do README (145
requisições por modelo, 0 abortadas, nos dois).

## 3. O que é diferente, e o impacto medido

### 3.1 Desempenho

**Teste:** `cmp_sweep` (8B + 3B sempre ativos, trace sintético de 60 s, eager nos dois).

| taxa | backend | req/s | TTFT médio | TPOT médio | E2E médio |
|---|---|---|---|---|---|
| 5 | SGLang / vLLM | 4,24 / 4,27 | 30,2 / 23,9 ms | 14,2 / 12,2 ms | 5,48 / 4,70 s |
| 10 | SGLang / vLLM | 9,21 / 9,20 | 31,9 / 25,2 ms | 16,6 / 13,0 ms | 6,40 / 5,02 s |
| 20 | SGLang / vLLM | 17,93 / 18,24 | 39,2 / 30,2 ms | 25,0 / 15,6 ms | 9,62 / 6,03 s |

Exemplos do README: `static` (2× 8B, 10 req/s) com TPOT 24,9 × 16,9 ms; `elastic` com 25,7 × 18,7 ms;
`prism1` (2× 3B, trace real de baixa carga) com TPOT **8,7 × 13,5 ms** e TTFT **34,5 × 61,3 ms**, ambos a favor do SGLang.

**Interpretação crítica:**
* A vazão é a mesma em todos os casos: a carga não satura nenhum dos dois.
* Sob carga, o vLLM 0.30 decodifica bem mais rápido, o que é coerente com kernels mais novos
  (FlashAttention 3 no H200 × FlashInfer 0.1.6).
* Em batch pequeno com modelo de 3B, o custo por token do modo eager do vLLM, mais o overhead do
  adaptador (1.3), supera esse ganho e o SGLang vence.
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
3. Antes de publicar números comparativos, **repetir as medições** (≥ 3 execuções), separar o efeito do
   engine com um SGLang recente e perfilar o adaptador (1.3), principalmente o TTFT sob concorrência.
4. Avaliar o sleep mode do vLLM para recuperar os CUDA graphs (−28% TPOT), testando a convivência com o
   kvcached.
5. Testar TP > 1 antes de qualquer uso com modelos grandes (o worker pool vLLM recusa TP > 1).

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
  `f6d0ea37` (`wp_test` + teardown).
