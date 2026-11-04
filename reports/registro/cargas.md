# Catálogo de cargas

Uma entrada por carga (seção 5 do `PLANO_AGENTE.md`). Estatísticas e hash por `polyaxon/workload_stats.py <nível> --md`: o hash cobre (id, modelo, chegada, prompt, saída) de todas as requisições geradas, então duas execuções com o mesmo hash enviaram exatamente a mesma carga (conferido: as 37 execuções do `ovl_phases` rate0.5 de 28/10 têm o mesmo hash). Gerador: `polyaxon/overload_load.py` (chegadas abertas, Gamma com CV dado, saída exata com `ignore_eos`, prazo extra de 300 s), parâmetros dos cenários em `polyaxon/run_examples.sh` (passo `ovl_*`).

**Intensidade de memória.** `ρ_mem = Σ W_m / M` com `W` de `model_info.json` (Llama-3.1-8B: 14,96 GB; Llama-3.2-3B: 5,95 GB) e `M` = 140,4 GB (memória total da H200 no `nvidia-smi`). Como a seção 5.1 define `ρ_mem` só com os pesos, `ovl_mem` com 8 modelos e `ovl_mix` ficam abaixo de 1: a sobrecarga deles vem dos pesos **mais** o KV (pool de 10 GB por modelo). A coluna "com KV" usa `W_m + pool`. Nenhum cenário existente chega ao `ρ_mem` 1,5–3 pedido na seção 5.1 com a definição só de pesos; isso entra na F3 (decidir se a definição inclui `K_min`).

| Carga | Modelos | `ρ_mem` (pesos) | `ρ_mem` (com KV) | Sobrecarga de computação |
| --- | --- | --- | --- | --- |
| C1 `ovl_mem` (10) | 10 × 8B, 6 ativos no início | 1,07 | 1,78 | não |
| C1 `ovl_mem` (8 / 14) | 8 / 14 × 8B | 0,85 / 1,49 | 1,42 / 2,49 | não |
| C2 `ovl_phases` | 10 × 8B, 2 grupos de 5 | 1,07 (0,53 por grupo) | 1,78 (0,89 por grupo) | não |
| C3 `ovl_mix` | 8 × 8B + 2 × 3B | 0,94 | 1,65 | não |
| C4 `ovl_kv` | 4 × 8B, pool 40 GB | 0,43 | 1,57 | KV |
| C5 `ovl_compute` | 2 × 8B, pool 30 GB | 0,21 | 0,64 | sim (taxas 5–50 req/s por modelo) |
| T1 `ovl_trace_big` | 12 × 8B, 6 ativos | 1,28 | 2,13 | não |

## C1 `ovl_mem` — fome sem ociosidade
- Origem: sintética (`overload_load.py`), semente 42. Licença: n/a.
- Construção: N × Llama-3.1-8B-Instruct (padrão 10, 6 ativos), todos enviando o tempo todo; Poisson (CV 1); prompt U[256, 1024], saída U[128, 512]; janela 300 s; níveis 0,2 e 0,5 req/s por modelo.
- Tamanhos: uniformes, **não** amostrados de um trace (a seção 5.2 pede a distribuição de um trace para as cargas novas; as existentes ficam como estão para comparabilidade).
- Nível de referência: `reports/data/2026-10-28-ociosidade/ovl_mem/original/r1/rate0.2`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `d06a2a2d8e6d9b1d…`
- 599 requisições em 300 s (1.997 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 0.98 (mín 0.84, máx 1.19)
- Popularidade (fração das requisições): model_7 11.7%, model_10 11.4%, model_1 10.9%, model_9 10.9%, model_6 10.0%, model_5 9.8%, model_3 9.7%, model_8 9.2%, model_2 8.7%, model_4 7.8%
- Prompt (tokens): p10 325, p50 631, p90 958, p99 1017
- Saída (tokens, exata): p10 170, p50 326, p90 477, p99 509

## C2 `ovl_phases` — troca de grupo
- Origem: sintética, semente 42.
- Construção: 10 × 8B em 2 grupos contíguos de 5 (`--groups 2 --phase 150`), só um grupo envia por vez; janela 600 s; nível 0,5 req/s por modelo no grupo ativo. Tamanhos como C1.
- O CV por modelo (~4,3) é alto por construção: cada modelo fica 150 s sem chegadas a cada 300 s. Dentro da fase ativa as chegadas são Poisson.
- Nível de referência: `reports/data/2026-10-28-ociosidade/ovl_phases/original/r1/rate0.5`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `5024bc56c03d67ad…`
- 1564 requisições em 600 s (2.607 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 4.29 (mín 4.01, máx 4.79)
- Popularidade (fração das requisições): model_10 12.2%, model_7 10.8%, model_5 10.4%, model_3 10.3%, model_9 10.0%, model_1 9.7%, model_2 9.3%, model_6 9.1%, model_4 9.1%, model_8 9.1%
- Prompt (tokens): p10 339, p50 623, p90 935, p99 1017
- Saída (tokens, exata): p10 167, p50 321, p90 475, p99 509

## C3 `ovl_mix` — tamanhos diferentes, impasse
- Origem: sintética, semente 42.
- Construção: 8 × 8B a 0,2 req/s (5 ativos) + 2 × Llama-3.2-3B-Instruct a 0,12 req/s (`PRISM_OVL_RATE2`, 2 ativos); janela 300 s. Tamanhos como C1.
- Nível de referência: `reports/data/2026-10-28-ociosidade/ovl_mix/original/r1/rate0.2`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `b72e6327b8cbbb2f…`
- 549 requisições em 300 s (1.830 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 0.98 (mín 0.77, máx 1.14)
- Popularidade (fração das requisições): model_7 12.8%, model_1 11.8%, model_6 10.9%, model_5 10.7%, model_3 10.6%, model_8 10.0%, model_2 9.5%, model_4 8.6%, model_9 7.8%, model_10 7.3%
- Prompt (tokens): p10 326, p50 632, p90 948, p99 1017
- Saída (tokens, exata): p10 171, p50 325, p90 479, p99 509

## C4 `ovl_kv` — crescimento de KV
- Origem: sintética, semente 42.
- Construção: 4 × 8B, todos ativos, pool de KV de 40 GB por modelo; prompt U[2048, 4096], saída U[1024, 2048]; janela 180 s, prazo extra 600 s; níveis 0,25, 0,5 e 1 req/s por modelo.
- Nível de referência: `reports/data/2026-10-21-sobrecarga-real/sglang/ovl_kv/rate0.5`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `10d0d73bdec6b207…`
- 337 requisições em 180 s (1.872 req/s), 4 modelos
- CV entre chegadas por modelo: mediana 0.96 (mín 0.91, máx 1.07)
- Popularidade (fração das requisições): model_1 27.3%, model_2 25.8%, model_3 23.7%, model_4 23.1%
- Prompt (tokens): p10 2232, p50 3067, p90 3888, p99 4065
- Saída (tokens, exata): p10 1113, p50 1530, p90 1942, p99 2041

## C5 `ovl_compute` — computação
- Origem: sintética, semente 42.
- Construção: 2 × 8B, ativos, pool 30 GB; prompt U[256, 768], saída U[128, 384]; janela 120 s; níveis 5, 12,5, 25 e 50 req/s por modelo.
- Nível de referência: `reports/data/2026-10-21-sobrecarga-real/sglang/ovl_compute/rate25`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `c42d0d29d609a930…`
- 6040 requisições em 120 s (50.333 req/s), 2 modelos
- CV entre chegadas por modelo: mediana 1.01 (mín 1.00, máx 1.01)
- Popularidade (fração das requisições): model_1 51.2%, model_2 48.8%
- Prompt (tokens): p10 306, p50 508, p90 719, p99 764
- Saída (tokens, exata): p10 154, p50 257, p90 359, p99 382

## T1 `ovl_trace_big` — trace do benchmark do Prism
- Origem: `benchmark/multi-model/real_trace.pkl` do repositório do Prism (trace do benchmark e2e do artigo; licença: a do repositório do Prism). sha256 do arquivo: `e36022a9eb4bb40f…`.
- Transformação: os 12 adaptadores mais requisitados do trace inteiro, um por modelo, em ordem de popularidade (`--trace-adapters 12`, `build_adapter_trace_requests`); prompts e tamanhos do trace; escala de tempo 1 (600 s) e 0,5 (300 s); SLO enviado = `--slo-ttft`. 12 × 8B, 6 ativos.
- Nível de referência: `reports/data/2026-10-28-ociosidade/ovl_trace_big/original/r1/ts1`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `e20a7e27f16dbac4…`
- 1275 requisições em 600 s (2.125 req/s), 12 modelos
- CV entre chegadas por modelo: mediana 1.09 (mín 0.94, máx 1.80)
- Popularidade (fração das requisições): model_1 23.2%, model_2 20.5%, model_3 15.6%, model_4 9.4%, model_5 5.3%, model_6 5.2%, model_7 4.4%, model_8 3.6%, model_9 3.5%, model_10 3.4%, model_11 3.1%, model_12 2.8%
- Prompt (tokens): p10 5, p50 40, p90 428, p99 932
- Saída (tokens, exata): p10 20, p50 232, p90 513, p99 785
