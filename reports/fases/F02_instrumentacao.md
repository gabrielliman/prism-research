# F02 — Instrumentação, validador e estimadores

Data de início / fim: 2026-11-04 / 2026-11-04
Commits: nenhum ainda (o Gabriel commita). Código das execuções da F2: `cb7c666` + `reports/data/F02/codigo/submetido_sobre_cb7c666.patch` (hashes em `sha256_submetido.txt`). O `iso_latency.py` da rodada `f2-iso2` ganhou só a gravação do load average (`reports/data/F02/codigo/iso_latency_iso2.py`).

## Objetivo

Dar às fases seguintes o que elas precisam para medir e decidir:
- logs estruturados das decisões do controlador e das requisições;
- um validador que separa execuções válidas das inválidas pelo motivo certo;
- métricas com o SLO como parâmetro, nas três vistas da seção 7.1;
- os estimadores `Ĉ_at`, `p̂`, `q̂` e `λ̂`;
- as latências de referência por modelo;
- uma primeira visão de quanto a ordem entre políticas depende do SLO.

## Hipóteses

- H1. O validador consegue reproduzir, a partir dos logs, as classificações que já fizemos à mão (falhas conhecidas de 28/10, janelas degradadas da D6).
- H2. O custo de ativação é previsível pelo tamanho do modelo e pelas ativações em andamento, porque o model service carrega um modelo por vez (P10).
- H3. Observação 4.0: com SLO de TTFT de 1 s, toda requisição que chega a um modelo inativo já nasce violada.
- H4. O log de decisões custa menos de 2% da vazão.

## Mudanças de código

| Arquivo | O que muda | Variável / padrão |
| --- | --- | --- |
| `python/sglang/multi_model/scheduling/decision_log.py` (novo) | uma linha JSON por ciclo do controlador: memória por GPU (livre, prometida a ativações pendentes, disponível), estado e fila de cada modelo (espera mais antiga, prazo mais próximo, tempos desde a última chegada e o último término, tempo de residência), ações com o motivo e eventos "não coube" | `PRISM_DECISION_LOG=<caminho>`; **desligado por padrão** |
| `policy/simple_global.py` | chama o log nos pontos de decisão do `gen_actions`; só lê o estado que a política já calculava | nenhuma mudança de comportamento (teste abaixo) |
| `python/sglang/multi_model/scheduling/estimators.py` (novo) | funções puras: `activation_cost`, `prefill_time`, `queue_time`, `queue_time_hybrid`, `RateEstimator` | não é usado por nenhuma política ainda |
| `polyaxon/overload_load.py`, `benchmark/multi-model/benchmark.py` | `requests.json` passa a ter: horário de envio, SLO, prazo, classe, TTFT visto pelo cliente e horários de parede do servidor; `summary.json` tem `load_start_wall` | o `RequestFuncOutput` ganha `client_ttft`; nenhuma métrica antiga muda |
| `polyaxon/run_examples.sh` | log de decisões por nível (`$RESULTS/<nível>/decisions.jsonl`, `PRISM_DECISION_LOG=` desliga); verificação de saúde depois de cada nível (`health_after.log`); passo `iso_lat` | `PRISM_HEALTH_AFTER` (padrão 1), `PRISM_ISO_REPS` (padrão 5) |
| `polyaxon/extract_ovl.py` | início da carga pelo relógio de parede do gerador quando existe (a heurística antiga erra 5–9 s sob sobrecarga de computação); `utc_offset_h` | a heurística continua para execuções antigas |
| `polyaxon/submit.sh` | envia o `iso_latency.py` | — |

Scripts novos de análise:
- `validate_run.py`, `validate_campaign.py`: validador por execução e por campanha.
- `slo_metrics.py`, `slo_curves.py`: métricas e curvas de SLO.
- `activation_cost.py`, `iso_latency.py`, `iso_fit.py`: custo de ativação e latências de referência.
- `estimators_eval.py`, `overhead.py`: avaliação dos estimadores e do sobrecusto do log.
- `workload_stats.py`, `register_runs.py`: catálogo de cargas e registro de execuções.

Testes novos (sem GPU):
- `tests/controller/test_decision_log.py`: o `gen_actions` produz as mesmas ações com e sem o log, e a linha registrada confere.
- `tests/controller/test_estimators.py`: 7 testes dos estimadores.
- `tests/controller/bench_decision_log.py`: microbenchmark do custo do log.

## Configurações executadas

| Job (uuid) | Suíte | O que mede |
| --- | --- | --- |
| `f2-smoke` (`85d1302b`) | `f2_smoke_suite.tsv`: A0.1 no `ovl_phases` 0,5 req/s, com e sem o log | smoke test dos logs novos e do validador |
| `f2-overhead` (`e9fd9988`) | `f2_overhead_suite.tsv`: `ovl_compute` 25 req/s por modelo, log ligado/desligado alternados, 3 pares | F2.8 |
| `f2-iso` (`b7a2f10b`) | `f2_iso_suite.tsv`: 8B e 3B sozinhos, 5 repetições cada | F2.10, F2.4 (primeira rodada; rodou junto com os outros dois jobs) |
| `f2-iso2` (`23d61305`) | a mesma suíte, sozinha no nó | F2.4 (`p̂`) e as sondas `TTFT_iso`/`TPOT_iso` (D18; hoje só para S2L) |
| `f2-ded-a` (`dd623724`) | `f2_ded_a_suite.tsv`: C2, C4 e C5, cada modelo sozinho numa GPU dedicada | F2.10, base do S2 pelo artigo do Prism (D20) |
| `f2-ded-b` (`6318bd87`) | `f2_ded_b_suite.tsv`: T1, idem | F2.10 (D20) |
| `f2-ded-c` (`daabe342`) | `f2_ded_c_suite.tsv`: C1 e C3, idem | F2.10 (D20); os três `f2-ded` rodaram juntos no nó |

Dados antigos usados (logs brutos copiados de `/tmp` para `/mnt/scratch/scheduler/prism-raw/`, D16):
- rodadas `fix`, `fix2`, `fix3` e `fix5` de 28/10;
- limites de 28/10;
- jobs da F0 e da F1.

## Execuções

As 8 execuções de carga (`f2-smoke`, `f2-overhead`) estão VALIDA e registradas em `reports/registro/execucoes.csv`; o veredito completo está em `reports/data/F02/validador/f2-*.csv`. As 20 medidas isoladas (`iso_lat`) não são execuções de carga: todas terminaram sem nenhuma requisição com falha. As 48 execuções dedicadas (`f2-ded-*`) estão VALIDA (`reports/data/F02/validador/f2-ded.csv`); nelas o V12, que procura evidência de sobrecarga de memória, não se aplica, porque há um só modelo. Todas as requisições foram atendidas.

## Resultados

### F2.2 / F2.2a — Validador e teste retroativo (H1)

Veredito de 363 níveis, em `reports/data/F02/validador/retro.csv`:

| Conjunto | Resultado |
| --- | --- |
| Limites de 28/10, com gabarito (`erros.csv`: K1, OOM, `pretty_print`, quedas, S4, workers mortos) | **17 de 17** falhas conhecidas inválidas; **37 de 37** execuções limpas válidas |
| Rodada `fix3` (nó degradado, já excluída na D2) | 54 níveis INVALIDA_INFRA, todos na janela de 27/10 12:20–16:30; os 29 fora dela, válidos |
| `f1-trace` (D6) | 6 de 6 INVALIDA_INFRA (janela de 30/10 00:30–01:10) |
| Níveis que o critério antigo (`collect_reps.clean`) aprovava | 230 válidos; 13 INVALIDA_INFRA (janela da `fix3`); 4 INVALIDA_SISTEMA: S4 em dois níveis da referência de 28/10 (`fix2` `trace12-1` idle25 ts0.5; `fix5` `trace12-2` idle10 ts0.5), um worker preso num laço de `RetractDecode` que o GPU scheduler entregou a outros dois modelos (`fix2` `tp-mem-1b`, fora da referência) e a falha injetada de `f1p12b/on` |
| Níveis que o critério antigo reprovava | 61 de 61 inválidos |

`validate_campaign.py` sobre os dados da F1 (`reproducao`, `folga_ovl_mix`):
- C-V1 e C-V2 passam.
- O C-V3 rejeita políticas diferentes (idle10 × original: IC [+9,6; +19,5] pontos de SLO) e aceita a referência contra si mesma.
- Na referência de 28/10, 14 níveis saem dos agregados (13 da janela + 1 S4).

Duas correções feitas no caminho, ambas registradas:
- O relógio dos logs é local (UTC−7 até 1/11, UTC−8 depois), e as janelas estão em UTC (D11). A primeira versão do validador marcou 18 níveis da `fix5` como degradados por isso.
- O V15 confundia queda do servidor com preempção do job, e o V12 se aplicava a níveis de controle sem sobrecarga (D16).

Limitações:
- O V4 olha o mapa modelo → worker do GPU scheduler e não vê um worker que continua preso servindo o modelo anterior (o caso da `tp-mem-1b`; quem pegou foi o V3).
- O V6 só se aplica a partir da F7 (recusas).

### F2.1 — Logs estruturados

No smoke test (`f2-smoke`, A0.1, `ovl_phases`):
- O log de decisões teve 123 ciclos, com 15 ativações, 15 despejos e 87 "não coube", idênticos ao log de texto.
- V9: nenhum TTFT do servidor depois do primeiro token visto pelo cliente.
- V10: o atraso do envio até o servidor foi de 4–6 ms (p99).
- V11: o atraso de envio do gerador foi de 3–4 ms (p99).
- V14: a verificação de saúde passou antes e depois do nível.

No `ovl_compute` a 25 req/s por modelo, o atraso do envio até o servidor chega a 0,95 s (p99), perto da tolerância de 1 s do V10.

### F2.8 — Sobrecusto do log (H4)

`reports/data/F02/sobrecusto/sobrecusto.md`:
- **Medida direta:** 0,083 ms e 2,9 KB por ciclo, com 12 modelos e 50 requisições em fila cada (`tests/controller/bench_decision_log.py`). É 0,0017% de um ciclo de 5 s, no processo do controlador, separado dos workers da GPU.
- **Vazão ponta a ponta:** inconclusiva. Ajustando a ordem no job, o efeito do log é de +1,0%, com IC 95% de [−9,7%; +11,8%]. A vazão subiu de 5.671 para 6.679 tok/s ao longo do job (o nó ficou mais rápido), e 3 pares não bastam contra essa deriva.
- **Tempo do ciclo do controlador:** sem diferença detectável (20,6 ms com log e 22,4 ms sem); o ruído domina, com p99 de 100–400 ms nos dois braços.

### F2.3 — Custo de ativação `Ĉ_at` (H2)

6.547 ativações e 6.958 desativações de 66 jobs limpos (`reports/data/F02/cat/`):

| Grupo | n | p50 (s) | p90 (s) | p99 (s) | máx (s) |
| --- | --- | --- | --- | --- | --- |
| 8B (15 GB), nenhuma ativação na frente | 5.005 | 1,40 | 3,02 | 7,42 | 61,3 |
| 8B, uma na frente | 1.350 | 2,56 | 4,14 | 9,57 | 36,9 |
| 3B (6 GB), nenhuma na frente | 37 | 0,92 | 2,40 | 2,87 | 3,0 |
| Desativação sem drenagem (GPU scheduler) | 5.153 | 0,65 | 5,56 | 24,0 | 53,7 |
| Liberação de memória no worker (onde está a P11) | 6.958 | 0,55 | 1,51 | 9,78 | 38,9 |

- Modelo: `Ĉ_at = 0,46 + 0,063·W_GB + 1,14·ahead` s, ajustado por regressão pela mediana (D12).
- **Erro mediano fora da amostra: 11,8%** (p90 71%). Por grupo:
  - 8B sem ativação na frente: 9,9%;
  - com uma ou mais na frente: 37–51%;
  - 3B com uma na frente: 127%, com n = 26.
- O custo próprio do worker explica a duração (correlação de 0,91); a mensageria acrescenta ~3 ms.

### F2.10 — Base do SLO relativo: carga do próprio modelo em GPU dedicada (D20, D21)

O método completo está em `reports/registro/latencia_ref.md`.

**Medição:**
- seguindo o artigo do Prism (§7.1), cada modelo de cada carga recebe **as próprias requisições** do nível de referência da carga (mesmas chegadas e tamanhos);
- o modelo roda sozinho numa GPU dedicada, residente durante toda a execução;
- TTFT e TPOT têm as definições de todas as execuções.

**Agregação (D21):**
- o P95 por modelo saiu com dispersão grande entre modelos idênticos, provavelmente pela disputa de CPU entre os três jobs: no C1, o P95 do TPOT vai de 11 a 49 ms;
- por isso a base junta as requisições dos modelos idênticos da carga;
- **S2** usa o P95 dessa junção e **S2M** usa a mediana, que é estável (CV de 2–14% entre modelos idênticos).

| Carga | Modelo | TTFT p50 / p95 | TPOT p50 / p95 |
| --- | --- | --- | --- |
| C1 `ovl_mem` | 8B (10 modelos) | 35,3 / 69,8 ms | 10,4 / 25,7 ms |
| C2 `ovl_phases` | 8B (10) | 37,0 / 124,4 ms | 10,7 / 25,9 ms |
| C3 `ovl_mix` | 8B (8) | 34,6 / 81,8 ms | 9,9 / 22,3 ms |
| C3 `ovl_mix` | 3B (2) | 24,7 / 100,0 ms | 8,7 / 22,0 ms |
| C4 `ovl_kv` | 8B (4) | 114,1 / 178,1 ms | 10,7 / 21,4 ms |
| C5 `ovl_compute` | 8B (2) | 873,6 / 15 260 ms | 44,7 / 69,9 ms |
| T1 `ovl_trace_big` | 8B (12) | 25,1 / 64,3 ms | 10,4 / 24,1 ms |

- Os valores por modelo e a dispersão estão em `reports/data/F02/ded/latencia_ded.md`.
- **C5:**
  - A base é dominada pela fila do próprio modelo. Cada 8B recebe ~25 req/s, no limite da GPU sem CUDA graphs, e no `model_1` a fila não se desfez (TTFT mediano de 14,6 s).
  - Ela fica como está, com o mesmo critério para todas as cargas (Gabriel, D21).
  - No C5, o S2/S2M é frouxo no TTFT: a leitura vai pelo S1 e pela vista só TPOT (`reports/registro/observacoes.md` O2).
- **CUDA graphs:** continuam desligados (D22). As latências valem para esta configuração (`observacoes.md` O1).
- A mediana do TPOT (9–11 ms) concorda com a sonda sozinha da D18 (12,2 ms).

### F2.4 — Sondas sintéticas e `p̂`

**Como são medidas.** As sondas da D18 eram a base do S2 até a D20. Hoje servem ao `p̂` e à família de comparação S2L.
- Cada modelo roda sozinho e residente na GPU, com os mesmos flags do servidor das cargas `ovl_*` (sem CUDA graphs) e um servidor novo por repetição.
- O TTFT e o TPOT têm as mesmas definições das cargas, a partir dos instantes do servidor:
  - TTFT = fim do prefill − chegada ao servidor;
  - TPOT = (fim − fim do prefill) / tokens de saída.
- **`TTFT_iso(m, L)`:** uma requisição por vez (sem fila), com `L` de 64 a 4.096 tokens e saída de 4 tokens. É uma reta `a + b·L` ajustada por regressão pela mediana sobre 350 requisições por modelo.
- **`TPOT_iso(m)`:** mediana do TPOT com um único fluxo (lote de decode = 1), prompt de 512 e saída de 256 tokens, em 20 requisições por modelo.
- **No S2L** (o S2 da D18, só para comparação), a requisição `r` tem SLO de TTFT `k_T·(a_m + b_m·L_r)` e SLO de TPOT `k_D·TPOT_iso(m)`.
- Os dois são o piso desta configuração do servidor. Se ela mudar, é preciso medir de novo.

**`p̂`:** usa os mesmos pontos de uma requisição por vez e mais rajadas de k ∈ {2, 4, 8, 16} requisições, com 256 ou 1.024 tokens, enviadas juntas. O maior TTFT da rajada é o tempo de prefill do lote de k·L tokens.

Rodada `f2-iso2`, sozinha no nó, 5 repetições (`reports/data/F02/iso2/iso_fit.md`, `reports/registro/latencia_ref.json`):

| Modelo | `TTFT_iso(L)` | erro mediano / p90 | `p̂(N)` (N = tokens no lote) | erro mediano / p90 | `TPOT_iso` (1 fluxo / 8) | CV do TPOT entre repetições |
| --- | --- | --- | --- | --- | --- | --- |
| Llama-3.1-8B | 19,1 ms + 27,6 µs·L | 10,6% / 32,7% | 12,3 ms + 33,4 µs·N | 12,4% / 37,3% | 12,2 / 14,7 ms | 7,8% |
| Llama-3.2-3B | 16,9 ms + 12,5 µs·L | 13,2% / 32,4% | 11,8 ms + 17,1 µs·N | 18,0% / 38,6% | 9,9 / 10,0 ms | 8,0% |

- Os erros são de validação deixando uma repetição de fora por vez.
- Na primeira rodada (`f2-iso`), com os três jobs juntos no nó, o TPOT variou até 3× entre repetições, e o erro do `p̂` do 3B foi de 23,4%.
- Sem CUDA graphs, o decode com lote pequeno é limitado pela CPU: na primeira rodada, o 3B chegou a ficar mais lento por token que o 8B. Por isso medidas de referência rodam sozinhas (D18).

### F2.5 — Estimadores de fila `q̂` e de taxa `λ̂`

**`λ̂`** (`reports/data/F02/estimadores/lambda.md`). EWMA com janelas de 10 e 60 s; segue a curta quando ela passa de 2× a longa ou cai abaixo da metade (D15). Erro de previsão das chegadas em H = 15 s (MAE em requisições e normalizado):

| Carga | Estimador | Só janela longa | Últimos H s | Taxa média real (piso clarividente) |
| --- | --- | --- | --- | --- |
| C1 `ovl_mem` | 1,71 (57%) | 1,64 (54%) | 2,10 (70%) | 1,37 (46%) |
| C2 `ovl_phases` | 1,95 (50%) | 2,83 (72%) | 1,99 (51%) | 3,87 (99%) |
| T1 `ovl_trace_big` | 1,53 (58%) | 1,50 (57%) | 1,66 (63%) | 1,77 (67%) |

Leitura: com chegadas Poisson, a maior parte do erro é ruído. Em C1, o estimador fica ~25% acima do piso de quem conhece a taxa média real.

**`q̂`** (`reports/data/F02/estimadores/fila.md`). TTFT previsto na chegada × real, para requisições com fila na frente e modelo ativo; erro absoluto mediano em segundos (D17):

| Carga | n | Soma dos prefills | Taxa observada | Híbrido (adotado) |
| --- | --- | --- | --- | --- |
| C1 `ovl_mem` | 12 | 0,19 | 11,9 | 0,19 |
| C2 `ovl_phases` | 242 | 3,6 | 18,3 | 5,9 |
| C3 `ovl_mix` (P0D1) | 91 | 18,8 | 19,8 | 18,8 |
| T1 `ovl_trace_big` | 277 | 12,5 | 16,8 | 7,8 |
| C5 `ovl_compute` 25 req/s | 5.987 | 35,0 | 1,7 | 1,6 |

O erro alto em C3 e T1 vem de esperas com o modelo "ativo" mas sem KV (impasse T1, retiradas), que nenhum dos dois estimadores vê.

### F2.6 — Observação 4.0 (H3): confirmada

`reports/data/F02/observacao_4_0.md`, todas as execuções de 28/10:

| Cenário | Chegadas a modelo inativo | TTFT ≤ 1 s | TTFT p10 / p50 / p90 (s) |
| --- | --- | --- | --- |
| `ovl_mem` | 14.282 | 0,0% | 18,3 / 163 / 318 |
| `ovl_phases` | 5.051 | 0,0% | 5,2 / 14,8 / 42,7 |
| `ovl_mix` | 1.912 | 0,0% | 5,3 / 15,8 / 45,7 |
| `ovl_trace_big` | 14.819 | 0,0% | 7,9 / 77 / 232 |

- Nenhuma das 36.064 requisições que chegaram a um modelo inativo teve TTFT ≤ 1 s. O mínimo do `Ĉ_at` de um 8B já é de 0,89 s, e a mediana, de 1,40 s.
- O TTFT efetivo de quem chega a modelo frio é de 5 a 18 s no p10, porque ao `Ĉ_at` se somam a espera pelo ciclo do controlador (5 s), a liberação da vítima e a fila.
- Com S1, a fração de violações inevitáveis vai de 8% (`ovl_phases`, A0.2 e A0.3) a 36% (`ovl_trace_big` ts0.5, A0.1) das requisições.
- **Consequência para o S3:** a seção 5.4 define `S_TTFT = k_A·Ĉ_at`, com `k_A ∈ {0,5; 1; 2; 5}`. Isso dá 0,7–7 s para um 8B, abaixo do TTFT real de modelo frio. Na prática, a ativação sob demanda só cabe no prazo com `k_A ≥ 10–25`.

### F2.11 — Métricas com SLO parametrizado

`slo_metrics.py` calcula as três vistas (combinada, só TTFT, só TPOT), a decomposição das violações (ambos OK / só TTFT / só TPOT / ambos / não atendidas), a separação evitável × inevitável e os percentis normalizados pela base (P95 junto, D21), por nível e por modelo. As famílias são S1, S2 (base P95), S2M (base P50), S3 e S2L (sondas da D18).

**Regressão:** com S1, reproduz exatamente os números de 28/10, F0 e F1 em 182 níveis. A diferença máxima é de 6,5e-13 (TTFT p90); nas frações, zero (D13).

### F2.12 — Curvas S2, S2M e S3 retroativas (28/10)

Refeitas com as bases da D21. Figuras em `reports/data/F02/curvas/<cenário>_<nível>.png`: uma linha para o S2 e outra para o S2M, mais o S3. Tabelas em `curvas.csv` e `resumo.md`.

Frações médias das repetições válidas para três políticas:

| Cenário | Política | S1 combinada | S2 `k_T`=10, `k_D`=5 | S2 `k_T`=10, `k_D`=10 | S2 só TPOT `k_D`=3 | S2M `k_T`=10, `k_D`=10 | S2M só TPOT `k_D`=5 | S2M só TPOT `k_D`=10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ovl_phases` 0,5 | A0.1 | 71,5% | 72,0% | 72,0% | 98,7% | 69,6% | 83,3% | 99,8% |
| | A0.2 | 86,7% | 88,0% | 88,7% | 97,6% | 85,6% | 92,1% | 98,3% |
| | A0.3 | 79,4% | 80,1% | 80,1% | 99,0% | 77,8% | 95,5% | 99,9% |
| `ovl_mem` 0,2 | A0.1 | 64,0% | 64,3% | 64,5% | 94,8% | 61,8% | 42,1% | 99,0% |
| | A0.2 | 51,3% | 51,9% | 52,5% | 96,0% | 50,1% | 32,6% | 97,6% |
| | A0.3 | 24,1% | 23,5% | 23,6% | 96,4% | 22,5% | 31,6% | 99,7% |
| `ovl_mix` 0,2 | A0.1 | 2,2% | 2,1% | 2,1% | 2,6% | 1,7% | 1,7% | 2,6% |
| | A0.3 | 52,8% | 52,6% | 52,6% | 95,8% | 50,0% | 13,2% | 100,0% |
| `ovl_trace_big` ts1 | A0.1 | 79,8% | 79,9% | 80,6% | 95,6% | 76,8% | 74,4% | 98,5% |
| | A0.2 | 77,5% | 77,5% | 78,1% | 94,1% | 75,1% | 60,8% | 98,0% |
| | A0.3 | 72,4% | 72,4% | 72,7% | 98,6% | 70,9% | 63,2% | 99,4% |

1. **TPOT deixou de ser o gargalo.**
   - Com a base dedicada, o TPOT sob sobrecarga fica, na maior parte, abaixo de 3× o P95 dedicado (~75 ms) e entre 5× e 10× a mediana dedicada.
   - Na vista só TPOT, o S2 passa de 90% em `k_D = 3` em todo cenário e política (exceto a A0.1 no `ovl_mix`, que não atende quase nada); o S2M passa em `k_D = 10`.
   - Com a base antiga, nenhum `k_D ≤ 3` passava de 3% na vista combinada.
2. **TTFT.**
   - Com a base P95, `k_T = 2` já dá 130–250 ms e a curva do S2 é quase plana de 2 a 100. O que sobra são as chegadas a modelo frio, que custam segundos e nenhum `k_T` da grade cobre.
   - Com a base P50, o degrau fica entre `k_T = 2` e `k_T = 5`.
   - Em `k_T = 10` com `k_D = 10`, o S2 fica a menos de 2 pontos do S1 (1 s, 100 ms) em todo cenário. Isso porque `10 × P95` (0,6–1,2 s) é perto de 1 s.
3. **Ordem entre políticas.** Com `k_T ≥ 10`, a ordem é a mesma de S1 em S2 e S2M, salvo entre políticas empatadas a 1–2 pontos (`ovl_trace_big`, `ovl_mem` entre A0.1 e a folga de KV). A inversão do S3 no `ovl_mem`, com a troca por throughput melhor em prazos folgados, não muda: o S3 usa `Ĉ_at` no TTFT.
4. **Níveis aprovados (D23).**
   - A faixa cinza das figuras marca os níveis aprovados de cada família.
   - A grade calculada é mais larga, para mostrar onde as curvas ficam planas.

## Anomalias e investigações

1. **Morte do model service e V10 no `f2-overhead` (`log_off_1`, `log_on_2`).**
   - Causa: erro de medição. Sob sobrecarga de computação, a admissão atrasa, e o início da carga estimado pelos logs saía 5,6–8,8 s atrasado. A janela da carga ia além do fim real e alcançava o desligamento do servidor (a "morte" foi 0,9 s depois do fim da carga).
   - Correção: o início vem do relógio de parede do gerador (`extract_ovl.load_start`).
   - Verificação: os 6 níveis saem VALIDA, e o retroativo não muda.
2. **TPOT instável e erro do `p̂` do 3B na `f2-iso`.**
   - Causa: concorrência por CPU com os nossos outros dois jobs (decode limitado pela CPU, sem CUDA graphs).
   - Verificação: repetida sozinha (`f2-iso2`), o CV cai de 48% para 8%, e o erro fica dentro do critério (D18).
3. **Fuso dos logs (UTC−7/−8).** Erro de medição na primeira versão do V14, corrigido (D11) e conferido nas rodadas `fix3`/`f1-trace` e no smoke test de novembro (UTC−8).
4. **Worker preso entregue a outros modelos (`fix2` `tp-mem-1b`, código antigo).** É uma falha nova de sistema. Ela não reapareceu no código atual: nenhum dos 230 níveis válidos tem ativação presa. Fica registrada para a F4: o V4 não detecta esse caso, e cabe acrescentar à lista de erros se reaparecer.

Nenhuma investigação aberta.

## Critérios de aceitação

| Critério | Situação | Evidência |
| --- | --- | --- |
| Validador acerta 100% das falhas conhecidas nos dados antigos e não acusa falha nas execuções sabidamente limpas | **OK**: 17/17 e 37/37 no gabarito de 28/10; `fix3` e `f1-trace` como INFRA, como na D6 | `reports/data/F02/validador/retro.csv` |
| Erro mediano de `Ĉ_at` ≤ 20% | **OK**: 11,8% fora da amostra (grupos com ativação na frente: 37–51%) | `reports/data/F02/cat/cat_fit.md` |
| Erro mediano de `p̂` ≤ 20% | **OK**: 12,4% (8B), 18,0% (3B) | `reports/data/F02/iso2/iso_fit.md` |
| Sobrecusto da instrumentação ≤ 2% na vazão, medido com e sem logs | **OK pela medida direta** (0,0017% do ciclo do controlador), aceita pelo Gabriel no gate (D19); a vazão ponta a ponta ficou inconclusiva (+1,0%, IC [−9,7%; +11,8%]) | `reports/data/F02/sobrecusto/sobrecusto.md` |

## Decisão do gate: APROVADO (Gabriel, 2026-11-04), com a base e os níveis do S2 revistos depois (D20–D23)

Registro completo em `reports/registro/decisoes.md`, D19–D23.

1. **Família principal de SLO: S2.**
   - O S1 é sempre reportado ao lado, para comparar com outubro.
   - O S3 é família secundária, para a observação 4.0.
   - **Base revista depois do gate:**
     - D20: a carga do próprio modelo em GPU dedicada, como no artigo do Prism;
     - D21: as requisições dos modelos idênticos juntas, com S2 sobre o P95 e S2M sobre a mediana.
   - O método está em `reports/registro/latencia_ref.md`, que todo relatório com S2 cita.
2. **Níveis (revistos sobre as bases da D21, D23):**
   - S2: `k_T ∈ {2, 5, 10, 25}`, `k_D ∈ {1,5; 2; 3; 5}`;
   - S2M: `k_T ∈ {5, 10, 25, 50}`, `k_D ∈ {3, 5, 10, 20}`;
   - S3: `k_A ∈ {2, 5, 10, 25, 50}` (D19).
   - Os níveis da D19 para `k_T`/`k_D` (`{5, …, 100}`, `{3, …, 20}`) tinham sido escolhidos sobre a base antiga e foram substituídos.
3. **SLOs das classes (F8), provisórios:**
   - interativa: S2 com `k_T = 10` e `k_D = 5`;
   - lote: TTFT de 60 s, sem limite de TPOT.

   Antes da F8, a proposta volta ao Gabriel com os dados da F5–F7 (TODO F8.0).
4. **Estimadores:** limite de 20% mantido para `Ĉ_at` e `p̂`. O `Ĉ_at` com ativação na frente e o `q̂` em impasse ficam como limitações declaradas. As fases seguintes reportam o erro dos estimadores junto com o resultado das políticas.
5. **F2.8:** a medida direta do sobrecusto é aceita como evidência do critério de ≤ 2%. Não se roda a campanha intercalada.

## Pendências que passam para fases seguintes

- **F3:**
  - definição de `ρ_mem`: com só pesos, nenhum cenário atual passa de 1,3, e `ovl_mix`/`ovl_mem(8)` ficam abaixo de 1 (`reports/registro/cargas.md`);
  - V11 por carga: taxas ±5%, CV ±10% e popularidade (D10);
  - medir `Ĉ_at` e as latências de referência dos modelos de 14B/32B (C10), porque a extrapolação linear em GB não está validada.
- **F4:**
  - refatorar `simple_global.py` em retrato + função pura (pendência da F0);
  - o V4 não vê um worker preso no modelo anterior;
  - o `q̂` em impasse;
  - a reserva de 5% do kvcached na A1.1.
- **F5:**
  - toda campanha registra execuções com `register_runs.py`;
  - as curvas de F2.12 passam a ser regeneradas por `slo_curves.py` sobre os dados novos;
  - as campanhas usam os níveis da D23 (S2, S2M) e da D19 (S3), já marcados nas figuras do `slo_curves.py` (`APPROVED`);
  - todo relatório com o C5 em S2/S2M declara a limitação O2 (`reports/registro/observacoes.md`);
  - medidas de referência rodam sozinhas no nó (D18).
- **F6:**
  - sensibilidade de `λ̂` (janelas, razão de troca);
  - o S3 mostrou inversão de ordem no `ovl_mem`: as políticas por prazo precisam ser avaliadas em pelo menos um nível folgado.
- **F8:**
  - reapresentar ao Gabriel os SLOs das classes, provisórios na D19, antes de começar.

## Como reproduzir

```bash
# logs brutos (persistidos fora do git): /mnt/scratch/scheduler/prism-raw/{2026-10-28,2026-10-28-limites,F0F1,F2}
# jobs da F2 (um por linha; baixar um de cada vez)
PRISM_JOB_SUFFIX=-f2-smoke PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_smoke_suite.tsv PRISM_TIMEOUT=5400" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f2-overhead PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_overhead_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-f2-iso2 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_iso_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh   # sozinho no nó
for x in a b c; do PRISM_JOB_SUFFIX=-f2-ded-$x PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_ded_${x}_suite.tsv PRISM_TIMEOUT=14400" polyaxon/submit.sh; done
polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path /mnt/scratch/scheduler/prism-raw/F2/<job>
R=/mnt/scratch/scheduler/prism-raw; PY=/mnt/scratch/scheduler/opt-env/bin/python
# F2.2 / F2.2a
python3 polyaxon/validate_run.py --csv reports/data/F02/validador/retro.csv $R/2026-10-28-limites $R/2026-10-28/fix $R/2026-10-28/fix2 $R/2026-10-28/fix3 $R/2026-10-28/fix5 $R/F0F1
python3 polyaxon/validate_run.py --csv reports/data/F02/validador/f2-overhead.csv $R/F2/f2-overhead
python3 polyaxon/validate_campaign.py reports/data/F01/reproducao reports/data/F02/validador/retro.csv
# F2.3
python3 polyaxon/activation_cost.py extract reports/data/F02/cat/custos.csv fix=$R/2026-10-28/fix fix2=$R/2026-10-28/fix2 fix5=$R/2026-10-28/fix5 \
  f0=$R/F0F1/f0 f1repro=$R/F0F1/f1repro f1code=$R/F0F1/f1code codenew=$R/F0F1/codenew codeold=$R/F0F1/codeold f1b=$R/F0F1/f1b \
  f1loss=$R/F0F1/f1loss headroom=$R/F0F1/headroom headroom-f1=$R/F0F1/headroom-f1
$PY polyaxon/activation_cost.py fit reports/data/F02/cat/custos.csv reports/data/F02/cat
# F2.10 / F2.4
$PY polyaxon/iso_fit.py reports/data/F02/iso2 $R/F2/f2-iso2/outputs/iso_8b $R/F2/f2-iso2/outputs/iso_3b
cp reports/data/F02/iso2/latencia_ref.json reports/registro/latencia_ref.json
python3 polyaxon/validate_run.py --csv reports/data/F02/validador/f2-ded.csv $R/F2/f2-ded-a $R/F2/f2-ded-b $R/F2/f2-ded-c
$PY polyaxon/iso_dedicated.py reports/data/F02/ded $R/F2/f2-ded-a/outputs $R/F2/f2-ded-b/outputs $R/F2/f2-ded-c/outputs
cp reports/data/F02/ded/latencia_ded.json reports/registro/latencia_ded.json
# F2.5
D=reports/data/2026-10-28-ociosidade
python3 polyaxon/estimators_eval.py rate reports/data/F02/estimadores/lambda.md C1_ovl_mem=$D/ovl_mem/original/r1/rate0.2 \
  C2_ovl_phases=$D/ovl_phases/original/r1/rate0.5 C3_ovl_mix=$D/ovl_mix/original/r1/rate0.2 T1_ovl_trace_big=$D/ovl_trace_big/original/r1/ts1
python3 polyaxon/estimators_eval.py queue reports/data/F02/estimadores/fila.md reports/registro/latencia_ref.json C1_ovl_mem=$D/ovl_mem/original/r1/rate0.2 \
  C2_ovl_phases=$D/ovl_phases/original/r1/rate0.5 C3_ovl_mix=$D/ovl_mix/tp_P0D1/r1/rate0.2 T1_ovl_trace_big=$D/ovl_trace_big/original/r1/ts1 \
  C5_ovl_compute=reports/data/2026-10-21-sobrecarga-real/sglang/ovl_compute/rate25
# F2.6, F2.11, F2.12
python3 polyaxon/slo_metrics.py states $D reports/data/F02/observacao_4_0.md
for d in $D reports/data/F00/reproducao reports/data/F01/reproducao reports/data/F01/folga_ovl_mix reports/data/F00/folga_ovl_mix; do python3 polyaxon/slo_metrics.py regress $d; done
$PY polyaxon/slo_curves.py $D reports/data/F02/validador/retro.csv reports/data/F02/curvas
# F2.8
$PY polyaxon/overhead.py reports/data/F02/sobrecusto/sobrecusto.md $R/F2/f2-overhead/outputs $R/F2/f2-smoke/outputs
$PY tests/controller/bench_decision_log.py
# F2.7
python3 polyaxon/workload_stats.py <nível> --md     # entradas do reports/registro/cargas.md
python3 polyaxon/register_runs.py reports/data/F02/validador/f2-overhead.csv --fase F02 --commit cb7c666+diff --suite polyaxon/configs/f2_overhead_suite.tsv
# testes
$PY -m unittest tests/controller/test_decision_log.py; python3 -m unittest tests/controller/test_estimators.py
```
