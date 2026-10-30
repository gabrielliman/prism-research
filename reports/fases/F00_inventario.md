# F0.1 e F0.2 — Inventário do repositório e arbitragem por folga (2026-10-29)

Commit inventariado: `2ac0098` (branch `sglang-only`). Backend: só SGLang 0.3.4 do Prism (o vLLM foi removido em `80069cf`).

## 1. Árvore relevante

```
python/sglang/multi_model/
  multi_model_server.py, multi_model_server_args.py   servidor multi-modelo e flags (--policy simple-global, --enable-*)
  request_handler_worker_pool.py                       frontend: recebe a requisição HTTP, põe na fila Redis do modelo
  model_sevice.py                                      model service: carrega pesos (um modelo por vez, P10)
  memory_arbiter.py, kvcached_patches.py               árbitro entre processos + ajustes do kvcached (PRISM_MEMORY_ARBITER=1; desligado)
  scheduling/
    controller_global.py      controlador global: laço de PRISM_SCHEDULE_INTERVAL s, chama policy.gen_actions, aplica ações
    policy/simple_global.py   TODAS as políticas de residência (ver seção 3)
    model_queue_tracker.py    visão do controlador das filas de cada modelo (Req: chegada, slo, prompt/output_len, estado)
    action.py                 ActivateAction, DeactivateAction (preempt, drain_timeout), ResizeAction
    gpu/gpu_scheduler.py      escalonador local por GPU: fila de prioridade, admissão, ativação/desativação, detecção de mortos
    gpu/request_queue.py      fila de prioridade por GPU (seção 4, F0.2)
    gpu/worker_pool.py        worker pool: um processo SGLang por worker, reaproveitado entre modelos
  utils/model_info.json       tamanho dos pesos (GB) e do KV por token (cell_size) por modelo
python/sglang/srt/managers/scheduler.py   motor SGLang: prefill/decode, PrefillKVFull (R2.2), drenagem, devolução ao Redis (P6)
python/sglang/srt/model_executor/worker_pool_model_runner.py   ativação no worker (PRISM_ACTIVATION_WAIT_S)
polyaxon/
  submit.sh, prism_examples.yaml   submissão ao Polyaxon (kunumi/hpc4ai, fila axia/default, 1 H200)
  run_examples.sh                  passos (static, elastic, prism1/2, overload, ovl_*); suítes (PRISM_SUITE); health_gate
  configs/*_suite.tsv              suítes: <nome><TAB><VAR=valor ...>
  overload_load.py                 gerador de carga aberta (sintético ou trace), saída exata, prazo extra
  kvcached_probe.py                verificação de saúde do nó (10 processos inicializam o kvcached)
  extract_ovl.py                   extrai requests.csv, gpu.csv e events.csv (eventos dos logs) por nível
  collect_reps.py                  junta níveis limpos de várias rodadas (manifest.csv)
  summarize_reps.py                metricas.csv (por nível) e resumo.csv (por configuração)
  classify_errors.py               conta assinaturas de erro por nível (K1, OOM, pretty_print, worker morto, T1...)
  report_tables.py, plot_suite.py, plot_reps.py, plot_limits.py, ovl_plots.py   tabelas e figuras
benchmark/multi-model/             benchmark original do Prism (real_trace.pkl, trace.py, benchmark.py)
reports/                           relatórios, reports/erros.md (lista de problemas), reports/data, reports/figs
```

Não existe `tests/policy/` nem testes unitários das políticas; `test/` é o conjunto do SGLang original.

## 2. Variáveis `PRISM_*`

### 2.1 Do sistema (lidas no código Python)

| Variável | Padrão | Onde | Efeito |
| --- | --- | --- | --- |
| `PRISM_EVICTION` | `idle` | `simple_global.py:199` | estratégia de despejo: `idle`, `pressure`, `adaptive`, `fair`, `throughput` |
| `PRISM_IDLE_THRESHOLD` | 50 | `simple_global.py:183` | segundos sem requisição para despejar um modelo ativo |
| `PRISM_SCHEDULE_INTERVAL` | 5 | `controller_global.py:288` | ciclo do controlador (s); `run_examples.sh` usa min(5, limiar) quando o limiar é dado |
| `PRISM_ACTIVATION_HEADROOM_GB` | 0 | `simple_global.py:218` | GB exigidos além dos pesos para ativar |
| `PRISM_ACTIVATION_ACCOUNTING` | 1 | `simple_global.py:225` | R2.1: desconta ativações pendentes (pesos + 1 GB de KV) da memória livre; 0 = Prism publicado |
| `PRISM_SWAP_MARGIN` | 0,2 | `simple_global.py:201` | troca por throughput: demanda envelhecida precisa superar a perda em 20% |
| `PRISM_SWAP_MIN_RESIDENCY` | 20 | `simple_global.py:202` | s mínimos de residência antes de ser vítima de troca |
| `PRISM_SWAP_AGING_S` | 30 | `simple_global.py:203` | envelhecimento da demanda de quem espera |
| `PRISM_SWAP_PREEMPT` | 0 | `simple_global.py:204` | troca com preempção (RECOMPUTE) das requisições em execução |
| `PRISM_SWAP_DRAIN` | 0 | `simple_global.py:205` | troca com drenagem da fila da vítima |
| `PRISM_SWAP_DRAIN_TIMEOUT` | 15 | `simple_global.py:206` | limite da drenagem (s) |
| `PRISM_PRESSURE_MIN_IDLE` | 2 | `simple_global.py:212` | `pressure`: ociosidade mínima da vítima (s) |
| `PRISM_PRESSURE_COOLDOWN` | 10 | `simple_global.py:213` | s entre despejos para o mesmo modelo em espera |
| `PRISM_ADAPTIVE_K`, `PRISM_ADAPTIVE_MIN` | 3, 5 | `simple_global.py:214-215` | `adaptive`: limiar = K × p90 dos intervalos, mínimo 5 s |
| `PRISM_FAIR_QUANTUM` | 30 | `simple_global.py:216` | `fair`: quantum do rodízio |
| `PRISM_DETECT_DEAD_WORKERS` | 1 | `gpu_scheduler.py:195`, `scheduler.py:2202` | detecção de workers mortos (R1) e saída só do worker em exceção (R2.2) |
| `PRISM_ACTIVATION_WAIT_S` | 30 | `worker_pool_model_runner.py:143` | espera da ativação no worker |
| `PRISM_MEMORY_ARBITER` | 0 | `memory_arbiter.py:182` | árbitro de memória entre processos + `kvcached_patches.py` (elimina K1, custa até 16%) |
| `PRISM_GPU_HEADROOM_GB` | — | `memory_arbiter.py:72` | folga do árbitro |

Constantes sem variável (em `simple_global.py`): `SWAP_RESERVATION = 15 s`, `DEMAND_WINDOW = 30 s`, `ACTIVATION_KV_GB = 1`, `PENDING_ACTIVATION_TIMEOUT_S = 120`, `MEMORY_POOL_BUDGET = 6`, `migrate_policy = "memory_per_request"` (migração entre GPUs; inerte com 1 GPU).

### 2.2 Da infraestrutura de teste (`run_examples.sh`, `submit.sh`)

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `PRISM_STEPS` | `static elastic prism1` | passos a rodar (`ovl_mem`, `ovl_phases`, `ovl_kv`, `ovl_compute`, `ovl_trace`, `ovl_trace_big`, `ovl_mix`, ...) |
| `PRISM_SUITE` | — | arquivo `.tsv`: várias configurações em sequência no mesmo job |
| `PRISM_OVL_RATES` | por cenário | níveis de carga (req/s por modelo, ou escala de tempo nos traces) |
| `PRISM_OVL_N`, `PRISM_OVL_ON`, `PRISM_OVL_N2`, `PRISM_OVL_ON2` | por cenário | número de modelos e quantos começam ativos |
| `PRISM_OVL_MODEL`, `PRISM_OVL_MODEL2` | Llama-3.1-8B-Instruct, Llama-3.2-3B-Instruct | modelos dos cenários |
| `PRISM_OVL_RATE2` | 0,12 | taxa dos modelos pequenos do `ovl_mix` |
| `PRISM_OVL_DURATION`, `PRISM_OVL_DRAIN`, `PRISM_OVL_PHASE` | por cenário, 300, 150 | janela de carga, prazo extra, duração da fase |
| `PRISM_OVL_POOL`, `PRISM_OVL_MAX_MEM`, `PRISM_OVL_WORKERS` | 10, 67,28, N | pool de KV por modelo, `--max-mem-usage`, `--workers-per-gpu` |
| `PRISM_OVL_LOAD` | — | substitui os argumentos de carga do cenário |
| `PRISM_OVL_SLO_TTFT`, `PRISM_OVL_SLO_TPOT` | 1,0, 0,1 | SLO enviado ao servidor e usado na métrica |
| `PRISM_FAULT` | — | injeção de falha (`kill:<modelo>:<s>`, `ballast:<s>:<dur>`) |
| `PRISM_HEALTH_PROCS`, `PRISM_HEALTH_RETRY_S`, `PRISM_HEALTH_WAIT_S` | 10, 300, 7200 | verificação de saúde do nó (R2.4) |
| `PRISM_START_ATTEMPTS`, `PRISM_STARTUP_TIMEOUT` | 3, 1200 | tentativas de subir o servidor |
| `PRISM_NO_WORKER_POOL` | 0 | remove as flags do worker pool |
| `PRISM_TIMEOUT`, `PRISM_QUEUE_WAIT` | 5400, 43200 | limite do job e da fila do cluster |
| `PRISM_IMAGE`, `PRISM_JOB_ENV`, `PRISM_JOB_SUFFIX`, `PRISM_GPUS`, `PRISM_PYTHON_SRC` | `gabrielliman/prism:sglang0.3.4-cu121`, —, —, 1, `python/` | submissão |
| `PRISM_TIME_SCALES`, `PRISM_WORKERS_PER_GPU`, `PRISM_WP_GPUS`, `PRISM_PROBE_*`, `PRISM_KVCACHED_VIRTUAL_GB` | — | passos antigos (`overload`, `wp_test`, `kvcached_probe`) |

## 3. Políticas de residência existentes

Todas em `SimpleGlobalPolicy.gen_actions` (`simple_global.py:1006`), chamada a cada ciclo pelo controlador. Ordem dentro de um ciclo:

1. **Despejo por ociosidade** (`_check_idle_instance_eviction`): modelo ativo sem requisições na fila nem em execução e ocioso há mais que o limiar (fixo, ou adaptativo com `adaptive`). Desativação sem preempção.
2. **Memória livre** = `get_available_gpu_memory` − ativações pendentes (R2.1).
3. **Migração entre GPUs** (`memory_per_request`): inerte com 1 GPU.
4. **Ativação**: modelos inativos com fila, ordenados pela fração de violação dos últimos 3 s; quem recebeu uma troca vai primeiro (`swap_reservation_until`). Ativa se `pesos + headroom + 1 GB` cabem.
5. **Despejo alternativo** para os que não couberam (`unplaced_models`):
   - `pressure`/`adaptive`: o ocioso (≥ 2 s) há mais tempo (ou mais atrasado em relação ao próprio limiar);
   - `fair`: idem, e rodízio do ativo há mais tempo se alguém espera ≥ 30 s;
   - `throughput`: vítimas por tokens/s por GB (`_throughput_swaps`), com preempção e/ou drenagem.
6. As ativações dos modelos que receberam vaga por despejo acontecem num ciclo seguinte, quando a memória aparece.

A lógica **não** é uma função pura: lê `time.time()`, `get_available_gpu_memory` e estado interno mutável dentro de `gen_actions`. Isso precisa mudar em F2/F4 para cumprir a seção 0.4 do plano (retrato de estado + função pura de decisão).

**Mapeamento para as linhas de base do plano:**

| Id | Configuração |
| --- | --- |
| A0.1 | `PRISM_IDLE_THRESHOLD=50` (padrão) |
| A0.2 | `PRISM_IDLE_THRESHOLD=10` (ciclo 5 s) |
| A0.3 | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_SWAP_DRAIN=1 PRISM_ACTIVATION_HEADROOM_GB=3` (P0D1, a melhor variante D de 28/10) |
| A0.4 | A0.3 + folga de KV (`PRISM_ACTIVATION_HEADROOM_GB` a escolher em F4) |
| A0.5 | não existe (seção 4) |

## 4. F0.2 — A arbitragem por folga (Moore-Hodgson) no código aberto

**Resposta: não existe.** O código aberto tem uma fila de prioridade por prazo na GPU, mas não o algoritmo de Moore-Hodgson do artigo, e a admissão está desligada na prática.

**O que o artigo descreve** (§6.2, Algoritmo 2, `Prism.pdf` p. 83–84): fila compartilhada por GPU; ordena as requisições por prazo `d_i = a_i + s_i`; acumula o tempo de prefill `e_r = p_r · c_r`; quando a última requisição acrescentada perde o prazo, **remove do conjunto a de maior tempo de execução** e segue. O conjunto resultante minimiza o número de prazos perdidos.

**O que o código faz:**

1. `gpu/request_queue.py:21-30`, `RequestWrapper._calculate_priority`: prioridade = `arrival_time + slo − prefill_estimado`, com `prefill_estimado = prompt_len × 0,5/1024` limitado a [0,2; 2] s. É um **instante de início mais tardio**, ou seja, EDF ajustado por uma estimativa fixa de prefill (não depende do modelo).
2. `request_queue.py:116-202`, `admission_control`: tira requisições do heap em ordem de prioridade e as manda à fila do motor do modelo. **Não há o passo de remoção do Moore-Hodgson**: nenhuma requisição é descartada ou adiada por estar atrasada. A verificação de recursos é inerte, porque `net_available = float("inf")` (linha 137, com o comentário "the actual implementation doesn't seem to limit resources"). Só há dois filtros: modelos `deactivating`/`deactivated` ficam na fila, e um modelo com mais de 10 requisições na fila do motor (`_skip_model_threshold`) é pulado naquele ciclo.
3. `gpu_scheduler.py:159-170`: o laço chama `admission_control(..., allow_sending_when_activating=True)` a cada 10 ms. Esse caminho está **ativo** em todos os cenários `ovl_*` (`--enable-gpu-scheduler`).
4. No motor (`srt/managers/scheduler.py`), a fila de espera é FCFS: `schedule_policy` padrão `lpm` vira `fcfs` com o radix cache desligado (`schedule_policy.py:38-40`, e os cenários usam `--disable-radix-cache`). Há um descarte por SLO (`_should_abort_req`, `scheduler.py:960`, aborta se `agora + 0,5 − chegada > slo`), mas só com `--abort-exceed-slos`, que é `False` por padrão e não é usado.
5. O SLO que chega ao servidor é o `--slo-ttft` do gerador (1 s), igual para todas as requisições nos cenários `ovl_*` (exceto `ovl_trace` com o trace de 8 adaptadores, que envia os SLOs por modelo do benchmark).

**Consequências para o plano:**

- Com o SLO igual para todos e a estimativa de prefill limitada a 2 s, a ordem da fila é quase a ordem de chegada. O efeito da fila de prioridade nos nossos cenários deve ser pequeno.
- Como a fila de cada motor é limitada a ~10 pela regra de pular modelos, a arbitragem entre modelos na mesma GPU só age quando um modelo acumula mais de 10 requisições no motor.
- **A0.5 precisa ser implementada** antes de A6 (F7), como o plano prevê. Ela substitui o passo 2 acima: ordenar por prazo, acumular `p̂_r` (por modelo, de F2.4) e remover a de maior `p̂` quando o prazo estoura. As removidas seguem na fila (o artigo não diz o que acontece com elas; registrar a escolha em `decisoes.md` quando chegar a hora).

## 5. Fluxo de uma execução de ponta a ponta

1. **Submissão** (local): `PRISM_JOB_SUFFIX=... PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/<x>_suite.tsv PRISM_TIMEOUT=10800" polyaxon/submit.sh`. Copia `python/`, o benchmark, `polyaxon/*` e as suítes para uma pasta temporária e faz `polyaxon run -u`. O job roda `run_examples.sh` dentro da imagem `gabrielliman/prism:sglang0.3.4-cu121`, com `timeout PRISM_TIMEOUT`.
2. **Suíte** (`run_examples.sh:30-40`): cada linha vira uma chamada de `run_examples.sh` com as variáveis da linha e resultados em `$PRISM_RESULTS/<nome>/`.
3. **Preparação**: `pip install -e python`, HF_HOME com links para o cache compartilhado, `environment.txt` (nó, memória, versões), Redis local na porta 6379.
4. **Configuração** (`ovl_*`, `run_examples.sh:404-443`): gera `configs/<passo>.json` com N cópias do modelo (`on` para os primeiros), estima `model_info.json` dos modelos que faltam.
5. **Por nível de carga** (taxa ou escala de tempo):
   1. `health_gate`: 10 processos inicializam o kvcached ao mesmo tempo; se falhar, espera 300 s (até 2 h) — log em `health.log`;
   2. `start_server`: `sglang.launch_multi_model_server` com as flags do exemplo 3 do README (kvcached, GPU scheduler, controlador `simple-global`, model service, worker pool com um worker por modelo); até 3 tentativas;
   3. `nvidia-smi` a cada 1 s → `gpu.csv`; injeção de falha opcional;
   4. `overload_load.py`: carga aberta, saída exata (`ignore_eos`), prazo extra (300 s) → `requests.json`, `summary.json`, `load.log`;
   5. `stop_server` (mata o grupo de processos).
6. **Download** (local): `polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path <pasta>`, um job por vez.
7. **Análise**: `collect_reps.py` (níveis limpos de várias rodadas, `manifest.csv`) → `extract_ovl.py` → `summarize_reps.py` (`metricas.csv`, `resumo.csv`) → `report_tables.py`, `plot_suite.py`, `plot_reps.py`; `classify_errors.py` para as assinaturas de erro.

## 6. Formato dos logs e resultados de um nível (`<suíte>/<passo>/<nível>/`)

| Arquivo | Conteúdo |
| --- | --- |
| `requests.json` | uma linha por requisição: `id, model, arrival` (s desde o início da carga), `prompt_len, output_len, status` (`ok`/`unserved`/`failed`), `ttft, tpot, latency, generated, error` |
| `summary.json` | `args, elapsed_s, sent, ok, failed, unserved, offered_rps, served_rps, output_tok_s, ttft_mean/p50/p99, tpot_mean/p99, slo_attainment, per_model` |
| `load.log` | resumo legível por modelo (primeiro ok, SLO) |
| `gpu.csv` | `timestamp, memory.used [MiB], memory.total [MiB], utilization.gpu [%]`, 1 Hz |
| `server.log` | stdout/stderr do servidor (onde aparecem aborts do kvcached `cuMem*`, tracebacks) |
| `server_file.log.global_controller.log` | controlador: `ACTION: activate/deactivate ... Reason: ...`, `No suitable GPU found`, `GPU 0, mem <GB>`, `Throughput swap: ...`, estado das instâncias a cada ciclo (texto, não JSON) |
| `server_file.log.gpu_scheduler.log` | GPU scheduler: `Admitted N requests for <model>`, ativações/desativações, `Assign worker`, workers mortos, desativação superada |
| `server_file.log.model_service.log` | carga de pesos |
| `health.log`, `startup_diag.log` | verificação de saúde e tentativas de subida |
| `run.log`, `environment.txt`, `configs/*.json` | no nível do job |

Os logs não são estruturados (texto com horário de parede). Os eventos usados nas figuras vêm de expressões regulares em `extract_ovl.py`; o início da carga é alinhado pelas linhas `Admitted`. Não há id de requisição nos eventos de devolução ao Redis (`Evicted N requests back to Redis`), o que impede hoje de seguir uma requisição perdida (pendência das 25 perdas). F2.1 resolve isso com logs JSON.
