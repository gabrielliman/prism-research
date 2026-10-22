# Reprodução dos exemplos do README (2026-10-21)

## Resumo

Os três exemplos do README rodaram com sucesso no Polyaxon, em GPUs H200: os servidores subiram, os benchmarks terminaram sem erro e **nenhuma requisição foi abortada**. Os exemplos 1 (memória estática) e 2 (memória elástica) rodaram com as configs do README. O exemplo 3 (Prism completo) pede 8 GPUs e 18 modelos e foi adaptado para 1 e 2 GPUs.

Para chegar lá foi preciso corrigir o ambiente e o script de execução: modelos, cache, Redis e limpeza entre exemplos. O código do Prism não foi alterado para esses três exemplos.

## O que foi executado

| Item | O que foi usado |
| --- | --- |
| Onde | Polyaxon, projeto `kunumi/hpc4ai`, fila `axia/default`, GPUs NVIDIA H200 (141 GB). As 4090 locais estavam ocupadas por jobs de outro usuário. |
| Ambiente | Imagem `gabrielliman/prism:sglang0.3.4-cu121` (`docker/prism/`): o container do `install.md` (`lmsysorg/sglang:v0.3.4.post2-cu121`), com os passos do `install.md` já aplicados (`pip install -e "python[all]"`, kvcached branch `prism/shm`) e o Redis 7.2.7 |
| Execução | `polyaxon/run_examples.sh` (um passo por exemplo: `static`, `elastic`, `prism1`, `prism2`), submetido com `polyaxon/submit.sh` |
| Modelos | Cache HF do cluster (`/scratch/hpc4ai/hf_cache`). Os modelos base do README (Llama-3.1-8B, Llama-3.2-3B, Llama-3.2-1B) são restritos e não estão no cache, então foram trocados pelas versões Instruct de mesma arquitetura: Llama-3.1-8B-Instruct e Llama-3.2-3B-Instruct. |

Os quatro passos:

| Passo | Exemplo do README | Config | O que mudou em relação ao README |
| --- | --- | --- | --- |
| `static` | 1: dois modelos na mesma GPU, memória estática | `1_gpu_2_model_colocate_static.json`: 2× Llama-3.1-8B-Instruct, `--load-format dummy` | só o modelo (Instruct) |
| `elastic` | 2: dois modelos na mesma GPU, memória elástica (kvcached) | `1_gpu_2_model_colocate_elastic.json`: 2× Llama-3.1-8B-Instruct, pesos reais | só o modelo (Instruct) |
| `prism1` | 3: Prism completo, em 1 GPU | `1_gpu_2_model_our.json` (do repo): 2× Llama-3.2-3B-Instruct | 1 GPU em vez de 8; 2 modelos em vez de 18 |
| `prism2` | 3: Prism completo, em 2 GPUs | `8_gpu_18_model_our.json` restrito às GPUs 0 e 1: 6× Llama-3.2-3B-Instruct, 3 por GPU | 2 GPUs em vez de 8; 6 modelos em vez de 18; 3B no lugar do 1B |

Os passos `prism1` e `prism2` usam todas as flags do exemplo 3 do README: memória elástica, GPU scheduler, controlador global `simple-global`, model service, worker pool, memória compartilhada na CPU e `--max-mem-usage 67.28`.

Os benchmarks são os do README:
- **`static` e `elastic`:** trace sintético, `--req-rate 10 --seed 42`, 60 s, 600 requisições (145 para o `model_1` e 455 para o `model_2`).
- **`prism1` e `prism2`:** trace real (`--e2e-benchmark --real-trace real_trace.pkl`).

## Resultados

| Passo | Execução | GPUs | Servidor pronto | Requisições | Abortadas | Vazão | TTFT médio / P99 | TPOT médio / P99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `static` | `a1eaeb0c` | 1 | ~85 s | 600 | 0 | 9,0 req/s, 3.459 tok/s | 48 / 80 ms | 25,5 / 32,3 ms |
| `elastic` | `0ebc811b` | 1 | ~50 s | 600 | 0 | 9,0 req/s, 3.447 tok/s | 50 / 113 ms | 25,6 / 31,7 ms |
| `prism1` | `fb85c32f` | 1 | ~50 s | 318 | 0 | 0,53 req/s | 20 / 41 ms | 7,8 / 10,0 ms |
| `prism2` | `3c066764` | 2 | ~70 s | 741 | 0 | 1,23 req/s | 52 / 319 ms | 8,4 / 10,5 ms |

- **`static` e `elastic`** têm o mesmo desempenho, como esperado: com dois modelos sempre ativos, a memória elástica não muda a vazão. O `static` passou também numa segunda execução (`2701e682`).
- **`prism1` e `prism2`:** os processos internos do Prism (GPU scheduler, controlador global, model service) rodaram sem erros. No `prism2` houve workers ativos nas duas GPUs.
- **SLO:** nos passos `static` e `elastic` o benchmark imprime "SLO Attainment 0", porque o trace sintético não define metas de SLO. Não é um resultado.

**Confirmação posterior.** No branch `vllm-backend`, os mesmos passos rodaram de novo como base da comparação entre backends (`python/sglang/multi_model/vllm_backend/ANALISE_VLLM_VS_SGLANG.md`, seção 2.5), 3 vezes cada no SGLang:
- `prism1`: 318/318, TTFT médio 82–130 ms;
- `prism2`: 741/741, TTFT médio 68–155 ms;
- `static` e `elastic`: sem nenhuma abortada.

## O que precisou ser ajustado

Nenhum desses problemas é do Prism em si; todos vêm do ambiente ou do script de execução.

| Problema | Sintoma | Correção |
| --- | --- | --- |
| Ambiente fora do `install.md` | Um env conda montado do zero puxou versões de 2026 (transformers 5.x, huggingface-hub 1.x) e um pacote `pyairports` falso, publicado por terceiros com o mesmo nome no PyPI | Descartado; a imagem passou a partir do container do `install.md`, que tem as versões fixadas de 2024 |
| Fila do Polyaxon | O job falhou ao compilar: a fila `axia/hpc4ai` não existe | Fila `axia/default`, projeto `kunumi/hpc4ai` |
| Cache HF do cluster sem `version.txt` | O transformers 4.46 roda uma "migração" de cache ao ser importado, e o servidor cai com `RuntimeError: context has already been set` | Cada job usa um `HF_HOME` próprio, com links para os modelos do cache compartilhado e o arquivo `version.txt`; o cache compartilhado não é alterado |
| Redis | Primeiro faltava o Redis (`Connection refused`); depois o Redis 5 do Ubuntu 20.04 não aceitava os comandos do cliente atual (`HELLO`, `LPOP` com contagem) | Redis 7.2.7 compilado na imagem e iniciado antes dos exemplos, como o `install.md` faz com `docker run redis` |
| Processos de um exemplo sobrevivendo ao seguinte | Os exemplos 2 e 3 não subiam: `Port 30001/30002 is not available` (as portas NCCL do exemplo anterior continuavam ocupadas) | Cada servidor roda no seu próprio grupo de processos, que é encerrado inteiro; antes de subir o próximo, o script espera as portas ficarem livres |
| Benchmark do exemplo 3 | O comando do README sempre manda requisições para 18 modelos, mesmo quando o servidor tem só 2 ou 6 | `--model-paths model_1 … model_N`, opção do próprio `benchmark.py` para mandar só aos modelos servidos |
| Modelos restritos | Llama base sem token HF e fora do cache | Versões Instruct de mesma arquitetura |
| Escala do exemplo 3 | O README pede 8 GPUs e 18 modelos | Versões de 1 GPU (`prism1`) e 2 GPUs (`prism2`) |

## Limitações

- O exemplo 3 não rodou na escala do README (8 GPUs, 18 modelos). As versões de 1 e 2 GPUs usam as mesmas flags, mas não exercitam a migração de modelos entre muitas GPUs do mesmo jeito.
- Os modelos são Instruct, não base, e o 3B substitui o 1B. Os números de desempenho não são comparáveis aos do artigo, que usa outras GPUs.
- Cada passo tem 1 execução nesta reprodução. As repetições estão na análise vLLM × SGLang.

## Reprodução

```bash
cd /mnt/scratch/scheduler/prism-research
# exemplos 1, 2 e 3 em 1 GPU
PRISM_JOB_ENV="PRISM_STEPS='static elastic prism1' PRISM_TIMEOUT=5400" polyaxon/submit.sh
# exemplo 3 em 2 GPUs
PRISM_GPUS=2 PRISM_JOB_ENV="PRISM_STEPS=prism2 PRISM_TIMEOUT=3600" polyaxon/submit.sh
# imagem
docker/prism/build.sh   # PUSH=1 para publicar no Docker Hub
```

Resultados: `polyaxon ops artifacts -p kunumi/hpc4ai -uid <execução> -d outputs --path-to <pasta>`. Em cada passo ficam o `benchmark.log`, os `benchmark-results` e os logs do servidor.
