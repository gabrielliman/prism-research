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

---

# F3 — cargas novas (2026-11-05, propostas para o gate da F3; nenhuma aprovada ainda)

**Dry runs (F3.12, A0.1, jobs `9d3f7e73`, `e40d0408`, `e24c4752`):** os 8 níveis rodados são VALIDA e têm o mesmo hash dos emits locais abaixo. **6 de 8 travaram** (T1, impasse de memória, com os tamanhos realistas): C6, C7, C8, C9 sobre C6, T3 e T4. Depois da D29: o T2 (job `2cfa2343`) é VALIDA, sem travar (1201/1201); o C10 (job `f722128d`, depois da correção da P14) é VALIDA, mas trava em 25 s (T1, 18/927). Ver `reports/fases/F03_cargas.md`, anomalia 1.

Gerador: `polyaxon/workloads.py` (chamado por `overload_load.py`; `workloads.py emit` gera o nível sem servidor). Passos em `polyaxon/run_examples.sh` (`ovl_zipf`, `ovl_bursty`, `ovl_diurnal`, `ovl_classes`, `ovl_sizes`, `ovl_tr_*`). Checagem contra a especificação: `polyaxon/workload_check.py` (realizado = o nível, uma semente; processo = média de 20 sementes). Testes: `tests/workloads/test_workloads.py`. Os C1–C5 mantêm o hash pelo caminho novo do gerador (conferido).

**Tamanhos das cargas novas (C6–C8, C10, T3):** pares (prompt, saída) sorteados juntos, com reposição, do trace de conversas do Azure LLM 2023 (`polyaxon/traces/L_azllm_conv.csv.gz`, 19.366 pares, CC-BY-4.0), com teto de 4096/1024 tokens (seção 5.2: tamanhos de um conjunto público; D28). Fração truncada: prompt ~1%, saída ~0% (`summary.json`, `workload_info.capped_frac`). O C9 sobre C1 mantém os tamanhos uniformes do C1, para comparar com ele.

| Carga | Modelos | `ρ_mem` (pesos) | `ρ_mem` (com KV) | Sobrecarga de computação |
| --- | --- | --- | --- | --- |
| C6 `ovl_zipf` | 10 × 8B, 6 ativos | 1,07 | 1,78 | não |
| C7 `ovl_bursty` | 10 × 8B, 6 ativos | 1,07 | 1,78 | não (rajadas locais) |
| C8 `ovl_diurnal` | 10 × 8B, 6 ativos | 1,07 nominal (os modelos com demanda variam no "dia") | 1,78 | no pico (3,6 req/s) |
| C9 `ovl_classes` | como C1 ou C6 | 1,07 | 1,78 | não |
| C10 `ovl_sizes` | 2 × 3B, 3 × 8B, 2 × Qwen2.5-14B, 1 × Qwen2.5-32B; 5 ativos | ~1,29 (14B ≈ 29,5 GB, 32B ≈ 65,5 GB, estimados pelos parâmetros) | ~1,86 | não |
| T3 / T4 / T5 `ovl_tr_*` | 12 × 8B, 6 ativos | 1,28 | 2,13 | não |

## C6 `ovl_zipf` — popularidade Zipf com deriva gradual
- Origem: sintética, semente 42. Licença: n/a.
- Construção: taxa total R (nível; padrão 2 req/s = C1 0,2 × 10) repartida por Zipf(α = 1) entre os ranks. A cada `PRISM_OVL_DRIFT` = 60 s, os modelos nos ranks j e j+1 trocam, com j = 0, 1, …, 8, 0, …: depois de 9 trocas, o mais popular é o último e os outros subiram um rank. Chegadas: renovação Gamma (CV 1) sobre a intensidade acumulada de cada modelo. Janela de 600 s (10 períodos).
- Especificação × obtido (semente 42 / média de 20 sementes):
  - taxa 1,988 / 1,986 (alvo 2; ±5% OK);
  - CV 1,04 / 1,00 (alvo 1; OK);
  - fração por rank (processo): 0,341 0,168 0,111 0,086 0,072 0,060 0,048 0,044 0,037 0,034, contra Zipf 0,341 0,171 0,114 0,085 0,068 0,057 0,049 0,043 0,038 0,034 (ordem OK). Na semente 42 isolada, ranks vizinhos da cauda trocam de ordem (diferença < 1 ponto, ruído de amostragem).
- Nível de referência (emit local): `ovl_zipf/rate2`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `19331633c0e55051…`
- 1193 requisições em 600 s (1.988 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 1.04 (mín 0.82, máx 1.39)
- Popularidade no nível inteiro (a ordem gira; não é Zipf): model_2 32.1%, model_3 15.9%, model_4 11.9%, model_1 10.3%, model_5 7.5%, model_6 6.1%, model_7 4.3%, model_8 4.3%, model_9 4.1%, model_10 3.4%
- Prompt (tokens): p10 203, p50 1023, p90 2524, p99 4096
- Saída (tokens, exata): p10 53, p50 136, p90 422, p99 596

## C7 `ovl_bursty` — rajadas assíncronas
- Origem: sintética, semente 42.
- Construção: por modelo, um MMPP de 2 estados liga/desliga (Poisson interrompido):
  - período ligado exponencial de média 10 s, com taxa λ_on = 3 × a taxa média (0,6 req/s para 0,2);
  - período desligado de média 20 s, sem chegadas;
  - independente por modelo, começando no estado estacionário; janela de 600 s.
  - CV teórico entre chegadas: `sqrt(1 + 2 λ_on ω1 / (ω1 + ω2)²)` = 2,52 (Fischer e Meier-Hellstern, 1993).
- Parâmetros (D28): o plano pede CV 2–4. Com ligado 20 s / desligado 40 s (CV 3,4), o CV medido numa janela de 600 s fica 10% abaixo do teórico (viés de janela finita; só 48% das sementes dentro de ±10%). Com 10/20 s, o viés é −5% (88% das sementes dentro). Escolhido 10/20.
- Especificação × obtido (semente 42 / média de 20 sementes): taxa 2,032 / 1,967 (alvo 2; OK); CV mediano por modelo 2,28 / 2,34 (alvo 2,52; −9% / −7%; OK).
- Nível de referência (emit local): `ovl_bursty/rate0.2`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `611f85189aed24f0…`
- 1219 requisições em 600 s (2.032 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 2.28 (mín 2.17, máx 2.70)
- Popularidade (fração das requisições): model_7 16.7%, model_10 11.4%, model_3 11.2%, model_4 10.3%, model_5 10.3%, model_1 10.0%, model_8 9.4%, model_6 7.6%, model_9 7.6%, model_2 5.4%
- Prompt (tokens): p10 203, p50 1020, p90 2524, p99 4096
- Saída (tokens, exata): p10 53, p50 135, p90 423, p99 596

## C8 `ovl_diurnal` — entrada e saída gradual da sobrecarga
- Origem: sintética, semente 42.
- Construção:
  - taxa total `R (1 − 0,8 cos(2π t / 1200))`: um "dia" de 20 min que começa no vale (0,4 req/s no vale, 3,6 no pico, média R = 2);
  - popularidade fixa Zipf(1); renovação Gamma CV 1 sobre a intensidade acumulada; janela de 1200 s.
  - No vale, os modelos da cauda ficam dezenas de segundos sem chegadas, e o limiar de ociosidade de 50 s da A0.1 os despeja. Assim, o número de modelos com demanda sobe e desce com a taxa.
- Especificação × obtido (semente 42 / média de 20 sementes):
  - taxa 1,959 / 1,980 (OK);
  - razão pico/vale em faixas de ±5% do período: 11,0 / 8,9, contra 8,4 teórica. O nível isolado fica +31% (ruído do vale, com ~20 requisições); o processo fica +7% (OK).
  - O CV por modelo (mediana 1,43) não é alvo, porque a taxa varia.
- Nível de referência (emit local): `ovl_diurnal/rate2`
- Hash (sha256 de id, modelo, chegada, prompt, saída): `ba5d4878ce1ee7e5…`
- 2351 requisições em 1200 s (1.959 req/s), 10 modelos
- CV entre chegadas por modelo: mediana 1.43 (mín 1.10, máx 1.69)
- Popularidade (fração das requisições): model_1 33.6%, model_2 17.9%, model_3 10.8%, model_4 8.7%, model_5 7.7%, model_6 5.3%, model_7 4.5%, model_8 4.1%, model_10 3.7%, model_9 3.7%
- Prompt (tokens): p10 206, p50 1023, p90 2753, p99 4096
- Saída (tokens, exata): p10 54, p50 133, p90 425, p99 594

## C9 `ovl_classes` — classes interativa e de lote
- Origem: sintética, semente 42.
- Construção:
  - base: C1 (`PRISM_OVL_CLASS_BASE=mem`, padrão) ou C6 (`=zipf`);
  - cada requisição é "batch" com probabilidade f (`PRISM_OVL_BATCH_FRAC`, padrão 0,3; é um fator), sorteada num fluxo de números aleatórios próprio. **As chegadas e os tamanhos são os mesmos da carga base:** o hash é igual ao do C1 / C6, porque não inclui a classe;
  - lote: SLO de TTFT de 60 s, sem limite de TPOT (enviado como 3600 s);
  - interativa: o SLO do passo (S1, ou `PRISM_OVL_SLO_SPEC`).
- Métrica: família S4 em `slo_metrics.py` (`S4:kT=10,kD=5,bT=60`: interativa = S2; lote = TTFT `bT`, sem TPOT), com as classes provisórias da D19 (a confirmar na F8.0).
- Especificação × obtido (semente 42 / média de 20 sementes): fração de lote 0,279 / 0,300 sobre C1 (o nível isolado fica −2,1 pontos; o desvio-padrão amostral é de 1,9 ponto com 599 requisições), 0,283 sobre C6.
- Hash: C1 `d06a2a2d8e6d9b1d…` (599 requisições, 300 s); C6 `19331633c0e55051…` (1193 requisições, 600 s).

## C10 `ovl_sizes` — heterogeneidade de tamanho
- Origem: sintética, semente 42. Licenças dos modelos: Llama 3.1/3.2 Community License; Qwen2.5-14B-Instruct e Qwen2.5-32B-Instruct, Apache-2.0.
- Construção: `PRISM_OVL_GROUPS`, padrão 2 × Llama-3.2-3B, 3 × Llama-3.1-8B, 2 × Qwen2.5-14B e 1 × Qwen2.5-32B, nessa ordem de `model_i` (ativos 2 + 2 + 1 + 0). Todos a 0,2 req/s, Poisson, tamanhos do Azure LLM; janela de 600 s.
- Modelos (D29): baixados para `/scratch/hpc4ai/hf_cache` pelo job `1f15aae8` (`polyaxon/hf_download.sh`, sem GPU); a imagem roda com `HF_HUB_OFFLINE=1`, por isso o dry run anterior falhou.
- Suporte:
  - a arquitetura `qwen2` existe no SGLang 0.3.4 (`python/sglang/srt/models/qwen2.py`);
  - o `model_info.json` não tem o 14B e tem um registro errado do 32B (8 GB); o passo os estima no job (`estimate_model_info --write`);
  - a presença dos dois modelos no cache do cluster só se confirma no dry run (o `run.log` agora lista os modelos do cache).
- Especificação × obtido: taxa 1,545 / 1,585 (alvo 1,6; OK); CV 1,01 / 0,98 (OK).
- Hash: `b72f0d9356dd5e66…` (927 requisições, 600 s, 8 modelos).

## C11 `slo_sweep` — sensibilidade ao SLO (definição, não gerador)
- Não é uma carga nova. É o conjunto {C1, C6, C7} × famílias S2/S2M/S3 da seção 5.4, nos níveis da D23.
  - Políticas que não usam o SLO: as curvas saem depois da execução (`slo_metrics.py`), com uma execução por carga.
  - Políticas que usam o SLO: o SLO enviado vem de `PRISM_OVL_SLO_SPEC`.
- **Pendência:** o S2/S2M usa a base da carga em GPU dedicada **por cenário** (D20/D21, `latencia_ded.json`). Nenhuma carga nova tem base. É preciso rodar `PRISM_OVL_DEDICATED=all` para cada carga aprovada antes de usar S2/S2M nela (custo estimado no relatório F03).

## T2 LMSYS-Chat-1M — não baixado
- Licença: "LMSYS-Chat-1M Dataset License Agreement" (Hugging Face, acesso condicionado):
  - uso de pesquisa e comercial permitido;
  - **redistribuição proibida**;
  - o licenciante pode exigir a remoção das cópias.
  - 25 modelos, com o campo do modelo por conversa; sem tempos de chegada.
- Situação (D29): termos aceitos pelo Gabriel; baixado em 2026-11-05 para `/mnt/scratch/scheduler/datasets/lmsys_chat_1m/` (6 parquet, 1,4 GB; o token fica só em `~/.cache/huggingface/token`). Pela proibição de redistribuição, o trace derivado não entra no git (`.gitignore`: `polyaxon/traces/T2_*`). Ele fica só no disco, e o `submit.sh` o envia ao job.
- Transformação (`trace_adapt.py lmsys`):
  - os 12 modelos com mais conversas (de 25), em ordem → `model_1..12`;
  - contagem = fração real entre os 12 × 2 req/s × 600 s; chegadas de Poisson sintéticas;
  - tamanhos do 1º turno do próprio modelo, tokenizador do Llama-3.1-8B, amostra de 5000 conversas por modelo (semente 0).
- Popularidade (antes = depois): vicuna-13b 55,8%, koala-13b 9,2%, alpaca-13b 7,1%, chatglm-6b 4,1%, llama-13b 3,7%, vicuna-33b 3,5%, llama-2-13b-chat 3,4%, oasst-pythia-12b 3,0%, fastchat-t5-3b 3,0%, claude-1 2,7%, dolly-v2-12b 2,7%, vicuna-7b 1,9% (das conversas entre os 12).
- Hash do nível: `59ac14592e1ce780…`; 1201 requisições em 599 s (2.005 req/s), 12 modelos; CV mediana 1,01; prompt p10 4, p50 25, p90 238, p99 648; saída p50 123, p99 701.

## T3 `ovl_tr_azfn` — Azure Functions 2019
- Origem:
  - AzurePublicDataset, `azurefunctions-dataset2019.tar.xz` (release `dataset-functions-2019`), arquivo `invocations_per_function_md.anon.d01.csv` (sha256 no cabeçalho do trace normalizado);
  - baixado em 2026-11-05 para `/mnt/scratch/scheduler/datasets/azure_functions_2019/`;
  - licença CC-BY-4.0 (citar Shahrad et al., USENIX ATC 2020).
- Transformação (`polyaxon/trace_adapt.py azfn`, D28):
  - funções com gatilho HTTP, minutos 600–660 do dia 1, ordenadas por invocações na janela;
  - 12 ranks espaçados em escala log, numa faixa cuja razão topo/base é 8 (como 23%/2,8% do T1), posicionada para que o total dê 2 req/s × 600 s: ranks 823, 899, 981, 1072, 1170, 1278, 1396, 1524, 1664, 1817, 1984 e 2167, de 15.933;
  - **sem afinamento:** contagens, razões de popularidade e forma por minuto são as reais;
  - 1 min → 10 s (escala 1/6); dentro do minuto, chegadas uniformes, porque o trace não tem tempo abaixo do minuto (semente 0);
  - tamanhos do Azure LLM 2023, porque o trace de funções não tem tokens.
- Antes/depois (`polyaxon/traces/T3_azfn.stats.json`): CV das contagens por minuto idêntico por entidade (variação 0%), ordem de popularidade preservada. CV entre chegadas depois: 0,50–2,76 (mediana 1,22).
- Hash do nível: `0631e6b688129b5b…`; 1200 requisições em 599 s (2.003 req/s), 12 modelos; popularidade de model_1 19.2% a model_12 2.4%; prompt p50 1014, saída p50 125.

## T4 `ovl_tr_azllm` — Azure LLM inference 2023 (conversa)
- Origem: AzurePublicDataset, `data/AzureLLMInferenceTrace_conv.csv` (19.366 requisições em 1 h, 5,5 req/s, um único serviço). Licença: CC-BY-4.0 (citar Patel et al., Splitwise, ISCA 2024).
- Transformação (`trace_adapt.py window --kind azllm --win 20`, D28):
  - entidade i = i-ésima janela consecutiva de 20 s a partir do início do trace; cada janela é esticada × 30 até 600 s;
  - cada entidade mantém um processo de chegada real, o seu CV (a escala de tempo não muda o CV: variação 0%) e os tamanhos reais;
  - popularidade: a variação natural de taxa entre janelas (quase uniforme, de 10,5% a 2,7%; a primeira janela pega o início do trace).
- Hash do nível: `1242b8f1ec8592f4…`; 1138 requisições em 600 s (1.897 req/s); CV mediana 0,98; prompt p50 999, saída p50 194.
- Limitação: a popularidade não é real (serviço único). O T4 serve para chegadas e tamanhos reais.

## T5 `ovl_tr_burst` — BurstGPT
- Origem: BurstGPT v1 (`data/BurstGPT_1.csv` do repositório HPMLL/BurstGPT; 1,43 milhão de requisições em 61 dias). Licença: CC-BY-4.0 (citar Wang et al., BurstGPT). O trace tem só 4 entidades (ChatGPT/GPT-4 × log de API/conversa).
- Transformação (`trace_adapt.py window --kind burstgpt --win 600 --anchor target`, D28):
  - ChatGPT + log de API; falhas (0 tokens de resposta, 1,8%) removidas;
  - os tempos vêm em segundos inteiros e recebem ruído U[0, 1) s;
  - entidade i = i-ésima janela de 600 s, a partir da primeira hora cujo bloco de 2 h tem 2 req/s × 600 s requisições;
  - escala de tempo 1 (sem esticar).
- Hash do nível: `9476e33aaa181629…`; 1194 requisições em 600 s (1.990 req/s); CV mediana 0,82 (0,34–1,63); **prompt p10–p99 de 82 a 115 tokens, saída p50 57**.
- **Achado:**
  - na taxa alvo, o BurstGPT é dominado por um cliente de API regular (prompts quase fixos, CV < 1);
  - as rajadas do BurstGPT estão nas horas de pico (~7 req/s por janela de 600 s, CV 1,0–2,2), isto é, em taxa de sobrecarga de computação;
  - proposta no relatório F03: não usar o T5 como carga de memória e, opcionalmente, usá-lo como carga de computação (2–4 modelos, hora de pico).
