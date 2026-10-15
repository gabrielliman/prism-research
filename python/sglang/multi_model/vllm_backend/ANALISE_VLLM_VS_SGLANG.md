# Prism sobre vLLM × Prism original (SGLang): análise crítica

Este documento compara o backend vLLM (`--engine-backend vllm`, branch `vllm-backend`) com o Prism
original sobre SGLang 0.3.4, com base em testes executados nas mesmas condições. O objetivo é ser
honesto sobre o que **não** funciona ou funciona pior. Cada afirmação de equivalência tem um teste que
a comprova, e cada diferença tem uma medição do seu impacto.

## Resumo

* **Funciona e é equivalente** em 1 GPU: API e formato de resposta, ativar/desativar (com saída idêntica
  após reativar), liberação de memória, preempção RETURN/RECOMPUTE, memória elástica (kvcached), resize,
  GPU scheduler e política do controller (mesmo número de ativações/remoções no `overload`).
* **Limitação mais grave: Prism multi-GPU não funciona.** Sem worker pool e sem migração de modelo entre
  GPUs, o exemplo completo do README em 2 GPUs (`prism2`) **trava 38% das requisições** (284/741). O
  SGLang com worker pool completa 741/741. Parte do problema (22 requisições) é do próprio plano de
  controle do Prism sem worker pool e também ocorre no SGLang; as outras 262 são exclusivas do vLLM.
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
| Engine | SGLang 0.3.4.post2 modificado pelo Prism (vLLM 0.6.3 para carregar pesos) | vLLM 0.30.0 sem modificações, atrás do adaptador |
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

### 1.1 Sem worker pool e sem migração: o Prism multi-GPU trava

O backend vLLM não implementa o worker pool (processo genérico que ativa qualquer modelo) nem a troca de
GPU de um modelo na ativação (`SingleModelRunner.activate(gpu_id=...)`): um engine vLLM é construído
para um modelo e um device.

**Teste:** `prism2`, o exemplo completo do README restrito às GPUs 0–1 (6 modelos, trace real, 741
requisições). Para separar a causa, o SGLang foi executado com e sem worker pool
(`PRISM_NO_WORKER_POOL=1`).

| configuração | concluídas | presas | o que trava |
|---|---|---|---|
| SGLang com worker pool (README) | 741 | 0 | — |
| SGLang sem worker pool | 719 | 22 (`model_3`) | o controller pede `instance 1` de um modelo que só tem a instância 0 (HTTP 400 em loop a cada 5 s) |
| vLLM | 457 | **284** (262 `model_4`, 22 `model_3`) | o mesmo problema, mais a recusa em ativar o `model_4` na GPU 0 ("this vLLM engine runs on GPU 1") |

**Interpretação:**
* A política `simple-global` assume que qualquer modelo pode ser ativado em qualquer GPU (semântica do
  worker pool). Sem pool, ela gera ações impossíveis e o controller **repete a ação sem nunca desistir**
  (668 ações de ativação no vLLM, 306 no SGLang sem pool).
* As 22 requisições presas do `model_3` são um defeito do Prism no modo sem pool, independente do backend.
* As 262 do `model_4` medem o custo de não ter migração, que é específico do vLLM.
* Em 1 GPU (`overload`) isso não aparece, porque não há para onde migrar. O backend vLLM deve ser
  considerado **somente para 1 GPU por modelo** até que o worker pool seja implementado ou a política
  passe a respeitar os placements fixos.

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
| Subida com 8 modelos (`overload`) | 60–80 s (worker pool) | 130–165 s | ~2× |
| Subida com 6 modelos em 2 GPUs (`prism2`) | 70 s | 105 s | +50% |
| Pesos na CPU | uma cópia compartilhada por modelo (`--enable-cpu-share-memory`) | uma cópia pinned **por engine** | RAM ∝ engines |

A subida mais lenta tem duas causas. Os engines na mesma GPU sobem um de cada vez, por um lock no
adaptador: o vLLM mede a memória livre da GPU inteira. Além disso, cada engine carrega pesos do disco
e não de memória compartilhada (não há model service).

### 1.5 Semântica: diferenças e pontos não verificados

* **RETURN** tem a mesma semântica pelo código (`Scheduler._complete_ongoing_requests` monta o batch da
  fila mas não executa o forward): nos dois, requisições na fila terminam com 0 tokens e
  `finish_reason=length`. **Não medido** para requisições na fila; o teste só cobre a requisição em
  execução.
* **Resize de memória no modo estático** é ignorado (o vLLM fixa o número de blocos na partida). O
  SGLang lança erro nesse caso, então ambos efetivamente não suportam, só que de formas diferentes.
* **`BatchRunReq`/`BatchRetractDecodeReq`** são inferidos a cada step a partir do estado do scheduler do
  vLLM, não emitidos no momento da decisão. A informação que o controller recebe é aproximada.
* **`update_weights`, LoRA, overlap schedule, data parallelism, multi-nó, async loading, model service** não
  são suportados (rejeitados na partida).

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

1. **Não usar o backend vLLM em multi-GPU** antes de resolver 1.1. Há dois caminhos: implementar o
   worker pool (opção A discutida: engines dormindo por par modelo×GPU, com pesos compartilhados na CPU),
   ou fazer a política respeitar placements fixos. Também convém corrigir o loop de `instance 1` do
   controller, que afeta os dois backends.
2. Antes de publicar números comparativos, **repetir as medições** (≥ 3 execuções), separar o efeito do
   engine com um SGLang recente e perfilar o adaptador (1.3), principalmente o TTFT sob concorrência.
3. Avaliar o sleep mode do vLLM para recuperar os CUDA graphs (−28% TPOT), testando a convivência com o
   kvcached.
4. Testar TP > 1 antes de qualquer uso com modelos grandes.

## Reprodução

```bash
# Comparação completa (1 GPU): mesmos passos com cada backend
STEPS="cmp_parity cmp_sweep cmp_graph switch_static switch_elastic static elastic prism1"
PRISM_IMAGE=gabrielliman/prism:sglang0.3.4-cu121 PRISM_JOB_ENV="PRISM_BACKEND=sglang PRISM_STEPS='$STEPS' PRISM_TIMEOUT=9000" polyaxon/submit.sh
PRISM_IMAGE=gabrielliman/prism:vllm0.30-kvcached0.1.6 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS='$STEPS cmp_overhead' PRISM_TIMEOUT=9000" polyaxon/submit.sh
# overload (1 GPU) e prism2 (2 GPUs); SGLang sem worker pool: PRISM_NO_WORKER_POOL=1
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS=prism2 PRISM_TIMEOUT=5400" PRISM_IMAGE=... polyaxon/submit.sh
# Tabelas a partir dos outputs baixados (polyaxon ops artifacts -d outputs)
python3 polyaxon/compare/report.py <outputs SGLang> <outputs vLLM>
python3 polyaxon/analyze_overload.py <outputs>
```

Execuções usadas neste documento (Polyaxon `kunumi/hpc4ai`):
* SGLang: `4fcd2f95` (bateria), `235bc00b` (`prism1`), `9b084c94` (`overload`), `b5eb5501` (`prism2`),
  `211d4f8e` (`prism2` sem worker pool);
* vLLM: `27b57700` (bateria), `f73352ca` (overhead), `2bf77793` (`overload`), `d3a8ff52` (`prism2`,
  interrompido após 64 min travado).
