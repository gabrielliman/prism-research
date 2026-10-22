# Prism em sobrecarga: exemplo 3 em 1 GPU, SGLang e vLLM (2026-10-21)

## Resumo

Rodamos o exemplo 3 do README (Prism completo) numa H200 com 8 modelos e o trace real acelerado de 1× a 10×. Foram 9 execuções: 4 com o backend original (SGLang) e 5 com o backend vLLM. **Em todas, as 754 requisições foram atendidas em todos os níveis, sem nenhuma abortada.** A sobrecarga, porém, foi só parcial, e da mesma forma nos dois backends:

- **Memória: não houve sobrecarga.** O orçamento de 67,28 GB vale para cada modelo, não para a GPU. A GPU sempre teve pelo menos 37 GB livres, e todos os despejos de modelo foram por ociosidade.
- **Carga: só satura a 10×.** A 10× o servidor atende 64–80% das 12,6 req/s oferecidas e o TPOT dobra. De 1× a 4× ele acompanha a carga.
- **Resultado:** o SLO cumprido cai a 10× (36–92% conforme a execução). Até 4×, a variação entre execuções idênticas, por exemplo de 56% a 98% a 4×, é maior que o efeito da carga. A cauda de latência vem da partida a frio dos modelos desligados (2–24 s) e de travamentos de causa não identificada, que aparecem nos dois backends.

## Como os resultados foram gerados

Todas as execuções rodaram no Polyaxon (projeto `kunumi/hpc4ai`, fila `axia/default`), cada uma num job de **1 GPU NVIDIA H200 (141 GB)**, com o mesmo script, a mesma config e o mesmo trace. Só muda o backend.

| Item | SGLang (original) | vLLM (branch `vllm-backend`) |
| --- | --- | --- |
| Imagem | `gabrielliman/prism:sglang0.3.4-cu121`: o container do `install.md` (`lmsysorg/sglang:v0.3.4.post2-cu121`) + kvcached `prism/shm` + Redis 7.2.7 | `gabrielliman/prism:vllm0.30-kvcached0.1.6`: vLLM 0.30.0, torch 2.13, CUDA 13.0, kvcached 0.1.6 |
| Engine | SGLang 0.3.4.post2 modificado pelo Prism | vLLM 0.30.0 atrás do adaptador (`--engine-backend vllm`) |

Comum aos dois:

| Item | O que foi usado |
| --- | --- |
| Script | passo `overload` de `polyaxon/run_examples.sh`, submetido com `polyaxon/submit.sh` |
| Config | `polyaxon/configs/1_gpu_8_model_overload.json` (8 modelos na GPU 0) |
| Servidor | flags do exemplo 3 do README (`--enable-elastic-memory --use-kvcached-v0 --max-mem-usage 67.28 --enable-gpu-scheduler --enable-controller --policy simple-global --enable-model-service --enable-worker-pool`), com `--workers-per-gpu 8` em vez de 4 (ver [Bug com 4 workers](#bug-com-4-workers)) e `--num-gpus 1` |
| Carga | `benchmark/multi-model/benchmark.py --e2e-benchmark --real-trace real_trace.pkl --model-paths model_1 … model_8`: o trace real do Prism, 754 requisições em 600 s a 1× |
| Análise | `polyaxon/analyze_overload.py` sobre os `output-requests/*.json` (TTFT e TPOT de cada requisição) e o log do controlador global |

**SLO.** Cada modelo tem o SLO do próprio trace (`trace.py`, `generate_e2e_benchmark_reqs`): o P95 de referência × 5, o padrão do benchmark. Isso dá TTFT de 109 a 243 ms e TPOT de 27 a 57 ms, conforme o modelo. Uma requisição só conta como cumprida se atende aos dois.

**Isolamento.** Cada nível de aceleração sobe um servidor novo e derruba o processo inteiro no fim, para que um nível não herde estado do anterior. Cada nível tem também um limite de tempo (duração do trace + 10 min), para que um travamento não segure o job.

**Execuções.**

| Execução | Backend | Data | Observação |
| --- | --- | --- | --- |
| `8929d7a4` | SGLang | 2026-10-15 | código original (antes do branch `vllm-backend`) |
| `9b084c94` | SGLang | 2026-10-15 | código do branch `vllm-backend` |
| `739a924e` | SGLang | 2026-10-16 | código do branch; repetição |
| `7bcb6dc0` | SGLang | 2026-10-16 | código do branch; repetição |
| `2bf77793` | vLLM | 2026-10-15 | sem worker pool (o vLLM ainda não tinha worker pool) |
| `d8402702` | vLLM | 2026-10-16 | worker pool, antes da correção do limite de KV por modelo |
| `c5a5f59b` | vLLM | 2026-10-16 | worker pool |
| `bfec63c4` | vLLM | 2026-10-16 | worker pool; repetição |
| `5469b118` | vLLM | 2026-10-16 | worker pool; repetição |

## Como sobrecarregamos

A sobrecarga foi pensada em dois eixos: mais modelos do que o orçamento de memória comporta, e o trace real acelerado até 10×.

**Memória.** Oito modelos na mesma GPU. A soma dos pesos (75 GB, medidos pelo `model_info.json` do Prism) passa do orçamento do README, `--max-mem-usage 67.28` GB, que corresponde a uma GPU de 80 GB como no artigo. Só 4 modelos começam ativos (33 GB de pesos). Os outros 4 começam desligados, e o Prism precisa ativá-los quando chega tráfego para eles.

| Modelo | Pesos | Início | Requisições no trace |
| --- | --- | --- | --- |
| `model_1` (Llama-3.1-8B-Instruct) | 15,1 GB | ativo | 296 |
| `model_4` (Llama-3.1-8B-Instruct) | 15,1 GB | desligado | 262 |
| `model_5` (Llama-3.1-8B-Instruct) | 15,1 GB | desligado | 120 |
| `model_2` (Llama-3.2-3B-Instruct) | 6,0 GB | ativo | 22 |
| `model_3` (Llama-3.2-3B-Instruct) | 6,0 GB | ativo | 22 |
| `model_6` (Llama-3.2-3B-Instruct) | 6,0 GB | ativo | 19 |
| `model_7` (Llama-3.2-3B-Instruct) | 6,0 GB | desligado | 11 |
| `model_8` (Llama-3.2-3B-Instruct) | 6,0 GB | desligado | 2 |

A mistura (três 8B e cinco menores) segue os perfis que o trace atribui a cada modelo. O 1B do trace virou 3B, porque o 1B não está no cache do cluster. Os dois modelos desligados mais carregados, `model_4` e `model_5`, recebem metade do tráfego.

**Carga.** O mesmo trace (754 requisições, 600 s) foi reproduzido a 1×, 2×, 4× e 10× (`--time-scale 1 / 0.5 / 0.25 / 0.1`). A carga oferecida vai de 1,3 a 12,6 req/s. O número de requisições e de tokens é o mesmo em todos os níveis; só muda a densidade no tempo.

## A sobrecarga foi real?

Em parte, e igual nos dois backends. **A sobrecarga de memória não aconteceu**: o orçamento de 67,28 GB não limitou nada. **A de carga só aconteceu a 10×**; de 1× a 4× a GPU acompanhou a carga oferecida.

### Memória: o teto não existia

O `--max-mem-usage` limita cada engine separadamente, ou seja, os pesos + KV de **um** modelo. Não é um teto da GPU:

- SGLang: `srt/model_executor/model_runner.py:161`;
- vLLM: vira o `gpu_memory_utilization` de cada engine (`vllm_backend/engine_adapter.py:212`).

A política global usa a memória total da GPU, 139,7 GB (`scheduling/controller_global.py:99`), e só ativa um modelo se houver memória livre de fato para ele. Os 75 GB de pesos dos 8 modelos cabem na H200.

Os logs das 9 execuções (36 níveis) confirmam:

- a memória livre da GPU nunca ficou abaixo de **36,9 GB** no SGLang nem de **45,2 GB** no vLLM, mais que o dobro do maior modelo (15,1 GB);
- nenhuma ativação esperou por memória, e nunca houve mais de 7 dos 8 modelos ativos ao mesmo tempo;
- todos os despejos foram por **ociosidade** (modelo sem requisições há mais de 50 s), nunca por falta de espaço;
- as decisões do controlador foram as mesmas em todas as execuções. Até 4×: 5 ativações e 4 despejos, de `model_2`, `model_3`, `model_6` e `model_7`, que têm pouco tráfego. A 10×: 4 ativações e 2 ou 3 despejos. `model_1`, `model_4` e `model_5` nunca saíram.

A troca de modelos aconteceu, mas porque 4 modelos começam desligados e por causa da regra de ociosidade. Não houve pressão de memória.

### Carga: só satura a 10×

Faixa entre execuções, por nível:

| Velocidade | Oferecido | Atendido SGLang | Atendido vLLM | Duração do benchmark (trace) | TPOT mediano SGLang | TPOT mediano vLLM |
| --- | --- | --- | --- | --- | --- | --- |
| 1× | 1,26 req/s | 1,22–1,24 req/s | 1,24 req/s | 607–616 s (600 s) | 18,8–21,3 ms | 14,1–15,7 ms |
| 2× | 2,51 req/s | 2,36–2,42 req/s | 2,37–2,44 req/s | 309–320 s (300 s) | 22,8–29,8 ms | 17,1–18,0 ms |
| 4× | 5,03 req/s | 4,31–4,58 req/s | 4,47–4,69 req/s | 161–175 s (150 s) | 25,8–34,7 ms | 18,9–22,8 ms |
| 10× | 12,57 req/s | 8,72–9,32 req/s | 8,00–10,00 req/s | 75–94 s (60 s) | 39,2–57,8 ms | 25,2–50,0 ms |

De 1× a 4×, o benchmark termina 7 a 25 s depois do trace. Isso é o tempo de gerar as últimas respostas, não fila. A 10×, o servidor atende 64–80% do oferecido, acumula 15–34 s de atraso, e o TPOT mediano dobra em relação a 1×. Aí sim a GPU satura. O vLLM 0.30 decodifica mais rápido que o SGLang 0.3.4 em todos os níveis, o que é coerente com a análise de backends (kernels mais novos).

### O que pesou na latência não foi a sobrecarga

Como a saída `i` do benchmark corresponde à requisição `i` do trace, dá para saber quando cada requisição chegou e cruzar com as ações do controlador. Esse cruzamento mostra três causas para as requisições lentas.

**1. Partida a frio.** A primeira requisição para um modelo desligado espera até ele ser ativado. A espera inclui o ciclo do controlador (a primeira ação sai ~5 s depois da primeira requisição) e a montagem do engine:

| Backend | 1× | 10× |
| --- | --- | --- |
| SGLang | 1,2–6,1 s | 2,6–9,3 s |
| vLLM sem worker pool | 2,7–5,2 s | 1,4–5,5 s |
| vLLM com worker pool | 0,9–11,8 s | 2,8–24,3 s |

No vLLM com worker pool, cada ativação monta um engine novo dentro do processo do slot, e sob carga isso compete com a inferência dos outros modelos. O vLLM sem pool só recopia os pesos para um engine que já está montado.

**2. Fila represada (só a 10×).** Enquanto um modelo está desligado, as requisições dele acumulam (26 do `model_4` numa das execuções) e entram todas de uma vez na ativação, disputando a GPU com os modelos já ativos.

**3. Travamentos sem causa aparente.** O `model_1` nunca é despejado e recebe 296 requisições, então é o melhor indicador de fila. Requisições do `model_1` acima do SLO de TTFT (214 ms), por execução e nível:

| Execução | Backend | 1× | 2× | 4× | 10× |
| --- | --- | --- | --- | --- | --- |
| `8929d7a4` | SGLang (código original) | 0 | 0 | 0 | 0 |
| `9b084c94` | SGLang | 24 | 40 | 12 | 18 |
| `739a924e` | SGLang | 18 | 2 | 2 | 56 |
| `7bcb6dc0` | SGLang | 32 | 59 | 70 | 98 |
| `2bf77793` | vLLM sem pool | 12 | 25 | 0 | 1 |
| `d8402702` | vLLM | 0 | 9 | 3 | 21 |
| `c5a5f59b` | vLLM | 0 | 0 | 0 | 1 |
| `bfec63c4` | vLLM | 16 | 3 | 11 | 53 |
| `5469b118` | vLLM | 13 | 42 | 38 | 0 |

A 1×–2× a carga é de 1–2 req/s numa H200, e mesmo assim há episódios de 1–5 s de TTFT. Na maioria dos casos esses episódios não ficam perto de nenhuma ativação ou despejo. Por exemplo, das 24 requisições lentas da `9b084c94` a 1×, nenhuma cai nos 15 s seguintes a uma ação, embora essas janelas contenham 21% das requisições do `model_1`. A 10×, parte deles coincide com ativações (a fila represada).

Os travamentos aparecem nos dois backends e em execuções com a mesma configuração. Duas execuções não têm nenhum de 1× a 4× (`8929d7a4` e `c5a5f59b`). Isso aponta para algo fora do engine: o plano de controle compartilhado (GPU scheduler, controlador, Redis) ou o nó do cluster. A causa não foi identificada.

## Resultados

**Todas as 9 execuções concluíram 754/754 requisições em todos os níveis, sem nenhuma abortada.** O SLO cumprido (TTFT e TPOT ao mesmo tempo):

| Execução | Backend | 1× | 2× | 4× | 10× |
| --- | --- | --- | --- | --- | --- |
| `8929d7a4` | SGLang (código original) | 98,4% | 98,0% | 96,3% | 87,1% |
| `9b084c94` | SGLang | 88,7% | 78,1% | 91,1% | 74,5% |
| `739a924e` | SGLang | 87,0% | 96,7% | 93,4% | 51,3% |
| `7bcb6dc0` | SGLang | 88,7% | 65,6% | 56,0% | 35,5% |
| `2bf77793` | vLLM sem worker pool | 95,4% | 89,0% | 97,3% | 91,8% |
| `d8402702` | vLLM (antes da correção do KV) | 98,3% | 95,2% | 94,6% | 67,2% |
| `c5a5f59b` | vLLM | 98,3% | 97,9% | 95,4% | 82,4% |
| `bfec63c4` | vLLM | 93,2% | 93,9% | 92,3% | 44,7% |
| `5469b118` | vLLM | 92,8% | 86,1% | 81,4% | 82,2% |

- **Variação maior que o efeito da carga até 4×.** Entre execuções idênticas, o SLO vai de 66% a 98% a 2× e de 56% a 96% a 4×. Uma execução isolada não mostra o efeito da carga nem permite comparar backends.
- **A 10×, quase todas caem.** Quem mais perde são os dois 8B que começam desligados e recebem metade do tráfego, porque pagam a partida a frio e a fila represada. A 10×, o `model_4` fica entre 15% e 78% no SGLang e entre 0% e 86% no vLLM. A exceção é o vLLM sem worker pool (91,8%), que ativa mais rápido; essa execução não foi repetida.
- **SGLang × vLLM.** Na média das execuções com worker pool, o vLLM fica à frente em todos os níveis, mas as faixas se sobrepõem. O vLLM também decodifica mais rápido (TPOT menor), o que reflete a idade dos engines (2026 × 2024), não o desenho do Prism (ver `python/sglang/multi_model/vllm_backend/ANALISE_VLLM_VS_SGLANG.md`).
- **Correção do KV por modelo no vLLM.** Antes dela, os modelos ativados na partida recebiam KV sem limite e tiravam espaço dos ativados depois: a 10×, o SLO foi de 67,2% (`d8402702`) para 82,4% (`c5a5f59b`).
- **A execução `8929d7a4` destoa entre as do SGLang.** Ela rodou com o código original; as outras três, com o branch `vllm-backend`, que mexe no plano de controle compartilhado, e em outros momentos do cluster. Os dados não separam o efeito do código do efeito do nó.

### Bug com 4 workers

Com `--workers-per-gpu 4`, o valor do README, e 4 modelos começando ativos, ativar um quinto modelo falha por falta de worker livre (`worker_pool.handle_activate_model`). A falha não é comunicada ao controlador global, que continua tratando o modelo como ativo, e as requisições desse modelo ficam presas para sempre: 131 de 754 a 1× na execução `bfbb4095` (SGLang). Todas as execuções deste report usam 8 workers, um por modelo.

## O que isso representa

O teste mostra que o Prism **troca modelos sob tráfego real sem perder requisições**, nos dois backends. Mas não testou o que o nome do cenário promete: a disputa por memória.

- **O que fica comprovado:** com 8 modelos numa GPU e 4 começando desligados, o controlador ativa sob demanda e despeja por ociosidade de forma determinística, e nenhuma requisição se perde até 10×. O GPU scheduler e a política funcionam igual atrás do adaptador vLLM.
- **Custo da troca:** a primeira requisição para um modelo desligado espera alguns segundos (tipicamente 5–6 s; até 24 s no vLLM com worker pool sob carga). A maior parte é a espera pelo ciclo do controlador, não a cópia dos pesos.
- **Limite de carga:** nesta GPU e com este trace, a saturação aparece entre 4× e 10× (5–13 req/s, somando os 8 modelos).
- **Confiabilidade dos números:** a variação entre execuções idênticas é grande demais para comparar configurações ou backends com 3 a 5 execuções. Parte dela vem dos travamentos sem causa identificada, que não têm relação com a sobrecarga.

**Limitações.** Os modelos são as versões Instruct e o 3B substitui o 1B do trace, porque são os que estão no cache do cluster. A H200 tem 141 GB, quase o dobro da GPU de 80 GB do artigo. O SLO é o do próprio trace (P95 de referência × 5); mudar o fator muda os percentuais. A comparação de backends mistura o desenho do adaptador com a geração do engine.

**Próximos passos sugeridos:**

1. **Sobrecarga de memória de verdade:** fazer os pesos dos modelos que precisam ficar ativos ao mesmo tempo passarem da memória livre da GPU, por exemplo 9 modelos de 8B (136 GB de pesos) recebendo tráfego ao mesmo tempo.
2. **Investigar os travamentos do `model_1`:** registrar a fila do GPU scheduler e os tempos do Redis por requisição numa execução a 1×.
3. **Corrigir o bug com 4 workers:** o GPU scheduler deve avisar o controlador quando uma ativação falha.

## Dados e reprodução

- Artefatos no Polyaxon (`kunumi/hpc4ai`): `polyaxon ops artifacts -p kunumi/hpc4ai -uid <execução> -d outputs --path-to <pasta>`.
- Tabelas de SLO: `python3 polyaxon/analyze_overload.py <pasta>/outputs` (precisa de numpy; roda na imagem).
- Rodar de novo: `PRISM_JOB_ENV="PRISM_STEPS=overload PRISM_TIMEOUT=5400" polyaxon/submit.sh`. Para o backend vLLM, acrescentar `PRISM_BACKEND=vllm` em `PRISM_JOB_ENV` e `PRISM_IMAGE=gabrielliman/prism:vllm0.30-kvcached0.1.6`.
