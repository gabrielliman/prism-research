# F03 — Catálogo de cargas

Data de início / fim: 2026-11-05 / 2026-11-05 (gate aguardando o Gabriel)
Commits: base `9d1768d` (sglang-only) + diff não commitado, salvo em `reports/data/F03/codigo/dry_9d1768d.diff`; o script de commit para o Gabriel é `/mnt/scratch/scheduler/f3_commit.sh` (branch `f3-cargas`, worktree `.claude/worktrees/f3-cargas`).

## Objetivo

Construir as cargas da campanha (seção 5 do `PLANO_AGENTE.md`): estender o gerador (F3.1), implementar C6–C11, adaptar traces reais pelo protocolo da seção 5.3, registrar cada carga em `reports/registro/cargas.md` e validar cada uma com um dry run da A0.1 (V8, V11, V12). O gate é [HUMANO]: o Gabriel aprova o conjunto de cargas da campanha.

Antes da F3, dois itens pendentes da F6a (D28):
- o registro das execuções da F6a em `execucoes.csv`;
- o `collect_reps.py`, que agora descarta os níveis inválidos.

## Ordem das tarefas (proposta e seguida) e o que cada carga exercita

Ordem: primeiro o que não depende de nada externo, depois os traces com licença livre, por fim o que depende de uma ação do Gabriel.

| # | Tarefa | Dependência | Situação |
| --- | --- | --- | --- |
| 1 | F3.1 gerador (`workloads.py`), recusa como estado final, classes, sementes, leitura de trace | — | feito |
| 2 | F3.2–F3.5 C6, C7, C8, C9 (sintéticas sobre o gerador novo) | 1 | feito |
| 3 | F3.7 C11 (definição sobre C1, C6, C7) | 2 | definido; falta a base dedicada das cargas novas para o S2/S2M |
| 4 | Licenças de T2–T5, antes de baixar | — | feito (abaixo) |
| 5 | F3.9 T3, F3.10 T4 e T5 (CC-BY-4.0) | 1, 4 | feito; T5 com achado |
| 6 | F3.11 estatísticas antes/depois, `cargas.md` | 2, 5 | feito |
| 7 | F3.12 dry runs (A0.1, 1 nível por carga, 3 jobs) | 2, 5 | ver "Execuções" |
| 8 | F3.6 C10 | modelos 14B/32B no cache do cluster | **bloqueado** (decisão 2 abaixo) |
| 9 | F3.8 T2 LMSYS | aceite dos termos pelo Gabriel | **bloqueado** (decisão 3 abaixo) |
| 10 | F3.13 este relatório | 1–7 | feito |

O que cada carga nova exercita (seção 0.9) e por que entra numa campanha de políticas de residência:

| Carga | Mecanismo exercitado | Políticas que ela separa |
| --- | --- | --- |
| C6 `zipf_drift` | popularidade que muda devagar: o conjunto residente "certo" muda a cada minuto; disputa de residência contínua (10 modelos, 6 cabem) | residência preditiva (A2.3, `λ̂`), despejo por perda esperada (A3) contra limiar de ociosidade fixo (A0.1/A0.2), que só reage |
| C7 `bursty` | rajadas assíncronas por modelo (ligado ~10 s, desligado ~20 s): ativação sob demanda dentro da rajada; ociosidade curta entre rajadas (abaixo de 50 s, acima de 10 s) | limiar de ociosidade (A0.1 × A0.2), custo de ativação × prazo (observação 4.0, A2.2, A9.2); é o cenário do artigo do Prism |
| C8 `diurnal` | entrada e saída gradual da sobrecarga: no vale, sobra memória; no pico, falta | se a política devolve e retoma memória com a taxa (histerese, A1.3), admissão no pico (A5) |
| C9 `slo_classes` | requisições de lote com prazo folgado misturadas às interativas, com as mesmas chegadas da carga base | A7 (classes e pesos), A5.3 (rebaixamento para lote); as linhas de base ignoram a classe |
| C10 `sizes_mix` | `W_m` e `Ĉ_at` diferentes em 10× (3B a 32B) | escolha da vítima por tamanho/valor (A3, A9.2, troca por throughput por GB), impasse com modelo grande (A1.1) |
| C11 `slo_sweep` | o mesmo conjunto de execuções sob S2/S2M/S3 em vários níveis | sensibilidade da ordem entre políticas ao SLO (seção 5.4) |
| T3 Azure Functions | chegadas reais por função (rajadas de minuto, CV 0,5–2,8) com popularidade real (razão 8) | o mesmo que C6/C7, com forma real em vez de modelo de processo |
| T4 Azure LLM | chegadas e tamanhos reais de um serviço de LLM; popularidade quase uniforme | realismo de tamanhos (prefill e KV); pouca separação por popularidade |
| T5 BurstGPT | na taxa alvo: cliente de API regular (CV < 1, prompts ~90 tokens) | **não exercita residência**; ver achado |

## Licenças (verificadas antes de baixar)

| Id | Fonte | Licença | Ação |
| --- | --- | --- | --- |
| T2 | LMSYS-Chat-1M (Hugging Face, acesso condicionado) | "LMSYS-Chat-1M Dataset License Agreement": pesquisa e uso comercial permitidos; **redistribuição proibida**; o licenciante pode exigir a remoção | **não baixado**; precisa do aceite do Gabriel; trace derivado fora do git (o `origin` é público) |
| T3 | Azure Functions 2019 (AzurePublicDataset) | CC-BY-4.0; citar Shahrad et al., ATC 2020 | baixado (143 MB, dia 1 extraído) |
| T4 | Azure LLM inference 2023 (AzurePublicDataset) | CC-BY-4.0; citar Patel et al., Splitwise, ISCA 2024 | baixado (conv e code, 1 MB) |
| T5 | BurstGPT v1 (HPMLL) | CC-BY-4.0; citar Wang et al. | baixado (`BurstGPT_1.csv`, 51 MB) |
| C10 | Qwen2.5-14B/32B-Instruct | Apache-2.0 | não estão no cache do cluster |

Dados brutos em `/mnt/scratch/scheduler/datasets/<id>/` (fora do git); traces normalizados (derivados, CC-BY) em `polyaxon/traces/`, com sha256 em `reports/data/F03/codigo/traces.sha256`.

## Hipóteses

1. O gerador novo reproduz os C1–C5 (mesmo hash) e gera C6–C9 com as estatísticas da especificação.
2. Cada carga nova de memória produz sobrecarga real com a A0.1 (V12: "No suitable GPU found" ou GPU ≥ 95%).
3. O gerador envia no tempo (V11) e as respostas são coerentes (V8) com tamanhos de prompt até 4096 tokens.

## Mudanças de código

| Arquivo | Mudança | Variável / padrão |
| --- | --- | --- |
| `polyaxon/workloads.py` (novo) | gerador puro: `zipf_drift`, `bursty` (IPP), `diurnal`, `trace`, tamanhos empíricos com teto, classes, uma semente por finalidade; `emit` gera o nível sem servidor | `--pattern constant` (padrão) reproduz o gerador antigo, sorteio por sorteio |
| `polyaxon/overload_load.py` | usa `workloads.build`; estado final `refused` (erro com `PRISM_REFUSED`, contrato para a F7); SLO da classe de lote | sem `--pattern`/`--batch-frac`: igual a antes |
| `polyaxon/trace_adapt.py` (novo) | T3, T4, T5 e a tabela de tamanhos; estatísticas antes/depois (`*.stats.json`) | — |
| `polyaxon/workload_check.py` (novo) | especificação × realizado (uma semente) × processo (20 sementes) | — |
| `polyaxon/run_examples.sh` | passos `ovl_zipf`, `ovl_bursty`, `ovl_diurnal`, `ovl_classes`, `ovl_sizes`, `ovl_tr_*`; config de grupos de modelos (C10); `run.log` lista os modelos do cache | `PRISM_OVL_DRIFT`, `PRISM_OVL_ALPHA`, `PRISM_OVL_BURST_ON/OFF`, `PRISM_OVL_AMP`, `PRISM_OVL_DAY`, `PRISM_OVL_CLASS_BASE`, `PRISM_OVL_BATCH_FRAC`, `PRISM_OVL_BATCH_TTFT`, `PRISM_OVL_GROUPS` |
| `polyaxon/submit.sh` | envia `workloads.py` e `polyaxon/traces/*.csv.gz` | — |
| `polyaxon/validate_run.py` | V5 aceita `refused`; V12 cobre os passos novos | — |
| `polyaxon/slo_metrics.py`, `extract_ovl.py` | família S4 (classes); coluna `slo_class` | — |
| `polyaxon/collect_reps.py` | só níveis VALIDA; `descartados.csv` | `PRISM_COLLECT_CRITERION=legacy` |
| `polyaxon/register_runs.py` | `politica_usa_slo` e SLO para `edf`/`lvf`; GPU | — |
| `tests/workloads/test_workloads.py` (novo) | 11 testes: processos (taxa, CV, fórmula do IPP), rotação, dia, classes sem mexer nas chegadas, sementes, traces | — |

Testes: `$PY -m unittest tests/workloads/test_workloads.py` (11 OK) e os 45 de `tests/controller`, `tests/robustness`, `tests/policy` (OK). Regressão do gerador: C1–C5 com o mesmo hash do `cargas.md` (`d06a2a2d…`, `5024bc56…`, `b72e6327…`, `10d0d73b…`, `c42d0d29…`).

## Configurações executadas

Dry run (F3.4/F3.12): só a A0.1 (`PRISM_IDLE_THRESHOLD=50`), S1 enviado, um nível por carga, uma repetição. A A0.1 basta: o dry run valida o gerador e a sobrecarga, não políticas (seção 0.9). Nenhuma linha de base anterior serve, porque as cargas são novas.

| Suíte (`polyaxon/configs/`, gitignored, `git add -f`) | Linhas |
| --- | --- |
| `f3_dry_a_suite.tsv` | C6 `ovl_zipf` rate2 · C7 `ovl_bursty` rate0.2 · C8 `ovl_diurnal` rate2 |
| `f3_dry_b_suite.tsv` | C9 sobre C1 `ovl_classes` rate0.2 · C9 sobre C6 (`PRISM_OVL_CLASS_BASE=zipf`) rate2 · T3 `ovl_tr_azfn` ts1 |
| `f3_dry_c_suite.tsv` | T4 `ovl_tr_azllm` ts1 · T5 `ovl_tr_burst` ts1 · C10 `ovl_sizes` rate0.2 |

3 jobs simultâneos (nenhum outro job do Prism no nó), ~3 job-horas.

## Execuções

Validador: `reports/data/F03/validador/dry_{a,b,c}.csv`. Dados brutos: `/mnt/scratch/scheduler/prism-raw/F3-dry/dry-{a,b,c}` (baixados um job por vez; uuid do pod conferido no `environment.txt`). Registro: 8 linhas da F03 em `reports/registro/execucoes.csv` (commit `9d1768d+diff`).

| Job | Nível | Validador | Hash = emit local | Atendidas | T1 congelado (informativo) |
| --- | --- | --- | --- | --- | --- |
| `9d3f7e73` dry-a | C6 `ovl_zipf/rate2` | VALIDA | sim (`19331633…`) | 245 / 1193 | 580 s |
| | C7 `ovl_bursty/rate0.2` | VALIDA | sim (`611f8518…`) | 200 / 1219 | 629 s |
| | C8 `ovl_diurnal/rate2` | VALIDA | sim (`ba5d4878…`) | 292 / 2351 | 1120 s |
| `e40d0408` dry-b | C9 sobre C1 `ovl_classes/rate0.2` | VALIDA | sim (`d06a2a2d…` = C1) | 599 / 599 | 0 |
| | C9 sobre C6 `ovl_classes/rate2` | VALIDA | sim (`19331633…` = C6) | 230 / 1193 | 433 s |
| | T3 `ovl_tr_azfn/ts1` | VALIDA | sim (`0631e6b6…`) | 261 / 1200 | 650 s |
| `e24c4752` dry-c | T4 `ovl_tr_azllm/ts1` | VALIDA | sim (`1242b8f1…`) | 121 / 1138 | 670 s |
| | T5 `ovl_tr_burst/ts1` | VALIDA | sim (`9476e33a…`) | 1194 / 1194 | 0 |
| | C10 `ovl_sizes` | **não rodou** (modelos fora do cache) | — | — | — |
| `2cfa2343` dry-d (depois da D29) | T2 `ovl_tr_lmsys/ts1` | VALIDA | sim (`59ac1459…`) | 1201 / 1201 | 0 |
| | C10 `ovl_sizes/rate0.2` | **não subiu**: `Too many open files` em 3 tentativas (P14) | — | — | — |
| `629687b2` investigação P14 | C10 e C3, 60 s, `PRISM_FD_TRACE=1` | (diagnóstico, fora do registro) | — | — | — |
| `f722128d` dry-e (depois da correção da P14) | C10 `ovl_sizes/rate0.2` | VALIDA | sim (`b72f0d93…`) | 18 / 927 | 869 s |

- V8, V11 e V12 OK nos 8 níveis. V12 vem de "No suitable GPU found": 510–866 por nível.
- Nenhuma requisição `failed` nem `refused`. As não atendidas são `unserved`: expiraram no prazo extra de 300 s.
- C10: o passo falhou na estimativa do `model_info` em 7 s, sem ocupar a GPU. O cache compartilhado não tem Qwen2.5-14B nem 32B, e a imagem força `HF_HUB_OFFLINE=1` (`docker/prism/Dockerfile:35`), daí o `couldn't connect to 'https://huggingface.co'`. Corrigido em D29: o cluster tem internet; os modelos foram baixados para o cache por um job sem GPU. Modelos no cache (do `run.log`): Llama-3.1-8B-Instruct, Llama-3.2-3B-Instruct, Qwen2.5-{0.5B,1.5B,3B,7B}-Instruct e Qwen3-{0.6B,4B,8B} (Qwen3 não roda no SGLang 0.3.4).

## Resultados

**Gerador (F3.11):** `reports/data/F03/workload_check_dry.txt`, sobre os níveis do cluster.

| Carga | Taxa (realizado / alvo) | Forma (realizado / alvo) | Leitura de processo (20 sementes) |
| --- | --- | --- | --- |
| C6 | 1,988 / 2 | CV 1,04 / 1; ordem por rank: dois vizinhos da cauda trocados | OK (taxa, CV, ordem Zipf) |
| C7 | 2,032 / 2 | CV 2,28 / 2,52 (−9%) | OK |
| C8 | 1,959 / 2 | pico/vale 11,0 / 8,4 (+31%) | OK (+7%) |
| C9 sobre C1 | 1,997 / 2 | fração de lote 0,279 / 0,30 (−2,1 pontos) | OK |
| C9 sobre C6 | 1,988 / 2 | fração de lote 0,283 / 0,30 | OK |
| T3 / T4 / T5 | 2,003 / 1,897 / 1,990 = trace | contagem por entidade = trace; ordem mantida; CV antes = depois (0% de variação) | n/a (determinístico) |

**Sobrecarga com a A0.1:** todas as cargas de memória têm disputa real de residência (V12). Mas 6 dos 8 níveis travaram (próxima seção). Nesses níveis, a fração atendida mede o travamento, não a política. Por isso este relatório não traz tabela de SLO.

## Anomalias e investigações

**1. Travamento T1 em 6 de 8 níveis (depois, em 7 de 10, com o C10): falha conhecida, disparada pelos tamanhos realistas.** Evidência: `reports/data/F03/inv_T1/`, com `resumo_niveis.txt`, `linha_do_tempo_C6.txt` e os scripts.

- **Sintoma:** as conclusões caem para zero entre 4 e 6 min de carga e não voltam.
  - Exemplo no C6: a última conclusão é em t = 294 s; daí até o fim, a GPU fica com 133,0 de 140,4 GB usados e 0% de utilização.
  - Os modelos residentes com fila também param: `model_2` tem 330 requisições não atendidas.
  - A métrica informativa T1 do validador marca de 433 a 1120 s.
  - Os níveis sem travamento (C9 sobre C1 e T5) têm T1 = 0 e atendem 100%.
- **Linha do tempo do C6:**
  - em t = 248 s, a ativação do `model_7` aperta a memória;
  - entre 247 e 272 s, há cinco *retracts* por falta de memória no decode (`model_3`, `model_6`);
  - depois disso, nenhum despejo: todo modelo residente tem fila, então nunca fica 50 s ocioso;
  - nenhuma ativação ocorre entre ~500 e ~870 `no_fit` por nível.
- **Classificação:** falha conhecida **T1** (`reports/erros.md`: impasse de memória criado pela política; a GPU fica cheia, o kvcached não tem página para o KV de nenhum prefill, a política original não despeja porque todos têm fila). Ela já estava encaminhada para a F4 (A1.1 reserva de KV na ativação, A1.2 detector de impasse).
  - Desta vez não se coletaram pilhas (`PRISM_STACK_DUMPS`). A classificação é pela assinatura, a mesma dos jobs `f1-freeze-3/4`.
- **Por que agora em todo nível:**
  - os tamanhos do Azure LLM 2023 têm prompt p50 ~1000, p90 ~2500 e até 4096 tokens, contra U[256, 1024] do C1, ou seja, cerca de 1,6× o KV mediano por requisição e uma cauda 4× maior;
  - com C1 e T1, o impasse aparecia com 8 ou 14 modelos; com os tamanhos reais, aparece com 10 e com 12.
  - Indício direto: a mesma A0.1 com as mesmas chegadas do C1 e tamanhos uniformes (C9 sobre C1) não trava. O T5 (12 modelos, prompts de ~90 tokens) também não.
  - Falta o teste A/B que isola o tamanho: C6 com tamanhos uniformes, 1 nível, ~15 min de GPU. Está proposto na decisão 4, não foi rodado.
- **C10 (job `f722128d`):** o mesmo T1, ainda mais cedo.
  - Em t = 12 s, a ativação do Qwen2.5-14B (`model_7`) leva a GPU a 132,9 GB, e há 1 *retract* em t = 21 s.
  - Depois de t = 25 s, a GPU fica em 0% até o fim. Só 18 de 927 requisições foram atendidas; o 32B nunca entra.
  - O único "error" no log é o `Error during cleanup` do desligamento, que o V2 exclui.
  - Com modelos de pesos muito diferentes, a política original enche a GPU ao ativar um modelo grande e não sai mais. É o caso que a A1.1 (reserva de KV) e a escolha da vítima por tamanho (A3, A9.2) precisam resolver.
- **T2 (LMSYS):** não trava (prompts curtos, p50 25 tokens). Atende 1201 de 1201.
- **Consequência:** o validador classificou os 6 níveis como VALIDA, porque o T1 é só informativo desde a F2. Os níveis valem como dry run do gerador (V8, V11, V12). Mas, enquanto a A1.1/A1.2 não existir, as cargas com tamanhos reais medem o impasse, não a política.
- **Correção:** nenhuma nesta fase. A correção é a F4, a próxima fase, e estas cargas passam a ser o teste de aceitação dela (a F4.5 pede zero impasses).

**2. P14: o C10 não subia (`Too many open files`).** Nova; registrada em `reports/erros.md`.
- **Sintoma:** com os modelos já no cache (job `2cfa2343`), o servidor do C10 morreu nas 3 tentativas, logo depois de carregar o 32B, com `OSError: [Errno 24] Too many open files`.
- **Hipótese e teste:** a menor execução que reproduz é uma partida do C10 com o rastreio de descritores (`PRISM_FD_TRACE=1`, job `629687b2`), com o C3 como controle. Resultado:
  - limite *soft* de 1024 no processo lançador (hard 524288);
  - os descritores do lançador sobem até 1011 no C10 e param em 612 no C3;
  - o `set_ulimit()` do SGLang (65535) não chega a esse processo.
- **Causa:** 4 modelos distintos em memória compartilhada de CPU, contra no máximo 2 nas cargas anteriores.
- **Correção:** `ulimit -Sn 65535` no `run_examples.sh`. É configuração do harness, sem efeito abaixo de 1024 descritores.
- **Verificação:** job `f722128d`. O C10 sobe em ~175 s com 5/5 modelos, o pico é de 1356 descritores, e o nível é VALIDA.

**2a. C10 sem modelos no cluster (antes da D29).** Infraestrutura, não código: 14B e 32B não estavam no cache, e a imagem roda offline (`HF_HUB_OFFLINE=1`). Na primeira versão deste relatório, o agente atribuiu isso, por engano, à falta de internet no cluster. Resolvido na D29 (download para o cache, job `1f15aae8`).

**3. Registros da F6a refeitos (D28):**
- os CSVs do validador e da triagem da F6a tinham se perdido (gitignored, ficaram no worktree da F6a). Foram refeitos dos dados brutos, com o `resumo.md` idêntico byte a byte;
- o relatório F06a diz "74 níveis, 73 VALIDA", mas a própria tabela de execuções soma 73 (72 VALIDA + 1 INVALIDA_SISTEMA). É um erro de contagem no texto. O relatório aprovado não foi alterado.

## Critérios de aceitação

| Critério | Situação | Evidência |
| --- | --- | --- |
| Cada carga com entrada completa em `cargas.md` | **FALHOU em parte** | **OK** para as cargas geradas: C6, C7, C8, C9, C10, T2, T3, T4, T5. C11 é definição de análise (a base dedicada do S2/S2M fica para a F5) |
| Estatísticas batem com a especificação (taxas ±5%, CV ±10%, popularidade preservada) | **OK** (leitura de processo, D29 item 5) | processo (20 sementes): todas as sintéticas OK; traces idênticos ao trace normalizado, com ordem preservada e variação de CV de 0%. O realizado de cada nível fica como informação: C6 (2 ranks vizinhos trocados), C8 (pico/vale +31%) e C9 (−2,1 pontos) estão dentro do ruído de amostragem |
| Dry runs válidos pelo validador | **OK: 10 de 10 cargas** (C6, C7, C8, C9 ×2, C10, T2, T3, T4, T5) | `reports/data/F03/validador/dry_{a,b,c,d,e}.csv`; T1 em 7 dos 10 (anomalia 1; níveis VALIDA pela D29, item 6). O C10 precisou da correção da P14 |

## Decisão do gate: APROVADO (Gabriel, 2026-11-05, D29)

**Respostas do Gabriel (2026-11-05, D29):**
1. Conjunto de cargas: proposta aceita.
2. C10: baixar os modelos. Download para o cache do cluster pelo job `1f15aae8`, sem GPU; depois, dry run do C10.
3. T2: termos aceitos. Baixado e adaptado (`trace_adapt.py lmsys`); falta o dry run.
4. Opção (a).
6. T1 continua informativo e os níveis travados ficam VALIDA. A ressalva está na D29.

5. Estatísticas julgadas pelo processo (média de 20 sementes).

Com os dry runs do C10 e do T2 (VALIDA) e a decisão 5, todos os critérios estão OK. O conjunto de cargas da campanha é o da decisão 1. Próxima fase: F4.

## T2 `ovl_tr_lmsys` (depois da D29)

- **Regra:**
  - os 12 modelos com mais conversas no LMSYS-Chat-1M (de 25), em ordem, → `model_1..12`;
  - contagem por modelo = fração real entre os 12 × 2 req/s × 600 s, então a popularidade é exatamente a real;
  - chegadas de Poisson sintéticas: o conjunto não tem tempos;
  - tamanhos do primeiro turno do próprio modelo (pergunta e resposta), tokenizados com o tokenizador do Llama-3.1-8B, numa amostra de 5000 conversas por modelo.
- **Popularidade:** vicuna-13b 55,8%, koala-13b 9,2%, alpaca-13b 7,1%, …, vicuna-7b 1,9% (razão ~30, contra 8 no T1 e no T3).
- **Tamanhos:** prompt p50 25 e p99 648 tokens; saída p50 123 tokens. São prompts curtos, como os do T1.
- **Nível:** 1201 requisições em 599 s; hash `59ac14592e1ce780…`; CV mediano 1,01; checagem OK (taxa, contagem por entidade, ordem).
- **Licença:** o trace derivado não vai para o git (`.gitignore`: `polyaxon/traces/T2_*`). O `submit.sh` o envia ao job a partir do disco.

## Proposta de conjunto de cargas e decisões para o Gabriel

**Decisão 1 — conjunto de cargas da campanha (proposta do agente):**

| Papel | Cargas | Motivo |
| --- | --- | --- |
| Núcleo (disputa de residência) | C1, C2, C3, T1 (existentes) + **C6, C7, C8, C9 (sobre C1 e sobre C6), T3** | cada uma separa um mecanismo diferente (tabela "o que cada carga exercita"); T3 é o único trace real novo com popularidade real |
| Controle (sem disputa de residência) | C4, C5 | como na F6a: medem efeitos colaterais de KV e computação |
| Análise | C11 = {C1, C6, C7} × S2/S2M/S3 | curvas depois da execução; precisa da base dedicada |
| Variante de realismo (baixa prioridade) | T4 | chegadas e tamanhos reais, popularidade quase uniforme |
| Fora (como carga de memória) | T5 | na taxa alvo, não tem rajadas (cliente de API regular, prompts ~90 tokens). Alternativa: T5 na hora de pico como carga de **computação** (2–4 modelos, ~7 req/s cada), se o Gabriel quiser uma carga real de computação |
| Bloqueadas | C10, T2 | decisões 2 e 3 |

**Decisão 2 — C10:**
- (a) **pôr Qwen2.5-14B-Instruct e Qwen2.5-32B-Instruct no cache do cluster** (`/scratch/hpc4ai/hf_cache`, ~95 GB, Apache-2.0; os passos `ovl_*` rodam offline). Recomendado: é o que o plano pede (heterogeneidade de `W_m` até ~65 GB);
- (b) redefinir o C10 com o que já está no cache: Qwen2.5-0.5B/1.5B/3B/7B + Llama 3B/8B. Os pesos vão de ~1 a 15 GB, mas não há modelo grande;
- (c) adiar o C10 para depois da F5.

**Decisão 3 — T2 (LMSYS-Chat-1M):** aceitar os termos com a conta do Gabriel no Hugging Face e pôr um token de leitura no ambiente; o agente então baixa e adapta. O trace derivado fica fora do git, porque a redistribuição é proibida e o `origin` é público. Alternativa: dispensar o T2. O T3 já dá popularidade real, mas de funções, não de modelos.

**Decisão 4 — tamanhos realistas × impasse T1:**
- (a) **manter os tamanhos do Azure LLM** e usar C6/C7/C8/T3 como teste da F4: a F4.5 exige zero impasses, e estas cargas disparam o T1 em todo nível. Recomendado: a F4 é a próxima fase, e isso dá a ela um caso reprodutível;
- (b) usar os tamanhos uniformes do C1 nas cargas novas: não travam hoje, mas contrariam a seção 5.2 ("não inventar tamanhos");
- (c) teto menor nos tamanhos (ex.: 2048/512).
- Em qualquer opção, o agente sugere o A/B de confirmação: C6 com tamanhos uniformes, 1 nível, ~15 min de GPU, 1 job.

**Decisão 5 — leitura do critério de estatísticas:** processo (20 sementes) ou realizado (o nível). Ver D28.

**Decisão 6 — o validador e o T1:** hoje o tempo congelado T1 é só informativo, então os 6 níveis travados passaram como VALIDA. Opção: classificar T1 > X s (ex.: 60 s) como INVALIDA_SISTEMA a partir da F4. É uma mudança de critério do validador, e o agente não a fez.

**Custo do que vem depois do gate (para planejar; nada submetido):**
- base dedicada para S2/S2M (`PRISM_OVL_DEDICATED=all`, um nível por modelo):
  - C6 e C7: 10 níveis de ~13 min cada;
  - C8: 10 de ~23 min;
  - T3: 12 de ~13 min;
  - C9 reaproveita as bases do C1 e do C6;
  - total ≈ **11 job-horas**, ~4 h de relógio em 3 jobs;
- C10 com os modelos no cache: 1 dry run (~20 min);
- T2: 1 dry run (~15 min).

## Pendências que passam para fases seguintes

- **F4:** o T1 dispara em todo nível com tamanhos reais (anomalia 1). A1.1/A1.2 devem ser testadas em C6, C7, C8, T3, além do C3 e do C1 com 14 modelos.
- **F5:** base dedicada (S2/S2M) das cargas aprovadas antes das curvas do C11.
- **F7:** o gerador já registra `refused` quando o servidor responde com `PRISM_REFUSED`; a A5 deve usar essa marca. V6 continua N/A.
- **F8.0:** as classes do C9 usam os SLOs provisórios da D19 (S4 em `slo_metrics.py`).
- **Registros:** os CSVs de registro e de validador agora vão para o git com `git add -f` (`/mnt/scratch/scheduler/f3_commit.sh`), para não se perderem de novo com o worktree.

## Reprodução

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
# dados brutos (CC-BY-4.0), em pastas novas fora do git
D=/mnt/scratch/scheduler/datasets; RAW=https://raw.githubusercontent.com
curl -sSfL -o $D/azure_llm_2023/AzureLLMInferenceTrace_conv.csv $RAW/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_conv.csv
curl -sSfL -o $D/burstgpt/BurstGPT_1.csv $RAW/HPMLL/BurstGPT/main/data/BurstGPT_1.csv
curl -sSfL -o $D/azure_functions_2019/azurefunctions-dataset2019.tar.xz \
  https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz
tar -xJf $D/azure_functions_2019/azurefunctions-dataset2019.tar.xz -C $D/azure_functions_2019/x invocations_per_function_md.anon.d01.csv
# traces normalizados (hash em reports/data/F03/codigo/traces.sha256)
$PY polyaxon/trace_adapt.py lengths --src $D/azure_llm_2023/AzureLLMInferenceTrace_conv.csv --out polyaxon/traces/L_azllm_conv.csv.gz
$PY polyaxon/trace_adapt.py window --kind azllm --src $D/azure_llm_2023/AzureLLMInferenceTrace_conv.csv --out polyaxon/traces/T4_azllm.csv.gz --n 12 --win 20
$PY polyaxon/trace_adapt.py window --kind burstgpt --src $D/burstgpt/BurstGPT_1.csv --out polyaxon/traces/T5_burst.csv.gz --n 12 --win 600 --filter "ChatGPT/API log" --anchor target --target-rate 2.0
$PY polyaxon/trace_adapt.py azfn --src $D/azure_functions_2019/x/invocations_per_function_md.anon.d01.csv --out polyaxon/traces/T3_azfn.csv.gz --n 12
# testes e checagem local das cargas (sem GPU)
$PY -m unittest tests/workloads/test_workloads.py
$PY polyaxon/workloads.py emit --models model_{1..10} --pattern zipf_drift --total-rate 2 --duration 600 \
  --lengths empirical:polyaxon/traces/L_azllm_conv.csv.gz --max-prompt 4096 --max-output 1024 --out /tmp/c6/ovl_zipf/rate2
$PY polyaxon/workload_check.py /tmp/c6/ovl_zipf/rate2
# dry runs (máx. 3 jobs do Prism no nó)
for j in a b c; do
  PRISM_JOB_SUFFIX=-f3-dry-$j PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f3_dry_${j}_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh
done
```
