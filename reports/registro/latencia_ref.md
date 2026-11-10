# Bases do SLO relativo (S2, S2M) e latências de referência das sondas: como são medidas e usadas

Todo relatório que use S2, S2M, S3 ou S2L cita esta página. A base atual vem da estratégia do artigo do Prism (§7.1; D20), agregada como na D21:

- **arquivo:** `reports/registro/latencia_ded.json`;
- **gerado por:** `polyaxon/iso_dedicated.py`;
- **execuções:** jobs `f2-ded-a`, `f2-ded-b`, `f2-ded-c`, de 2026-11-04.

As sondas sintéticas da D18 (`latencia_ref.json`) estão na última seção. Hoje elas servem só ao estimador de prefill `p̂` (F2.4) e à família de comparação S2L.

## Base atual: a carga do próprio modelo em GPU dedicada (D20, D21)

### O que é medido

O artigo do Prism faz assim: "we first ran its workload on dedicated GPUs to measure its P95 TTFT and TPOT latencies. [...] We then scaled these base values by a factor". Aqui, para cada carga C1–C5 e T1 e cada modelo da carga:

- **Requisições:** as do próprio modelo no **nível de referência** da carga (`reports/registro/cargas.md`).
  - O gerador monta a carga inteira, com a mesma semente e o mesmo nível, e envia só as requisições daquele modelo (`polyaxon/overload_load.py --only-model <m> --send-as model_1`). As chegadas, os tamanhos de prompt e os tamanhos de saída são exatamente os da carga original.
- **Servidor:**
  - um único modelo, residente durante toda a execução (`PRISM_IDLE_THRESHOLD=1000000`, nunca é retirado);
  - os mesmos flags das cargas `ovl_*`: `--disable-cuda-graph`, `--disable-radix-cache`, kvcached, controlador `simple-global`;
  - 1 worker por GPU, o pool de KV da carga e um servidor novo por modelo.
  - Isso é o passo `ovl_*` do `polyaxon/run_examples.sh` com `PRISM_OVL_DEDICATED=all`.
- **Definições:** são as de todas as execuções (`benchmark/multi-model/benchmark.py`). Os instantes vêm do servidor:
  - **TTFT** = `prefill_finish_timestamp − arrival_timestamp`, da chegada ao servidor até o fim do prefill. Inclui a fila do próprio modelo, mas não a rede;
  - **TPOT** = `(finish_timestamp − prefill_finish_timestamp) / output_len`.
- **Nível:** a base é medida só no nível de referência e fica **fixa entre os níveis de taxa** da carga. Medida em cada taxa, ela afrouxaria o SLO à medida que a carga sobe.

### Como a base é agregada (D21)

O P95 por modelo não é usado. Modelos idênticos da mesma carga davam P95 muito diferentes. No C1, por exemplo, o P95 do TPOT ia de 11 a 49 ms. A causa provável são os episódios de lentidão por disputa de CPU entre os três jobs do nó (decisão D21). Por isso:

- **S2:** a base é o **P95 das requisições atendidas de todos os modelos idênticos** (mesmo `model_path`) da carga, juntas (`pool_ttft_p95`, `pool_tpot_p95`). Os episódios lentos ficam na base, mas diluídos.
- **S2M:** a mesma junção, com a **mediana** (`pool_ttft_p50`, `pool_tpot_p50`). Entre modelos idênticos, a mediana tem CV de 2–14%, contra 25–214% do P95.

### Valores

| Carga | Modelo | Modelos juntados | Requisições | TTFT p50 / p95 | TPOT p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| C1 `ovl_mem` | 8B | 10 | 599 | 35,3 / 69,8 ms | 10,4 / 25,7 ms |
| C2 `ovl_phases` | 8B | 10 | 1564 | 37,0 / 124,4 ms | 10,7 / 25,9 ms |
| C3 `ovl_mix` | 8B | 8 | 466 | 34,6 / 81,8 ms | 9,9 / 22,3 ms |
| C3 `ovl_mix` | 3B | 2 | 83 | 24,7 / 100,0 ms | 8,7 / 22,0 ms |
| C4 `ovl_kv` | 8B | 4 | 337 | 114,1 / 178,1 ms | 10,7 / 21,4 ms |
| C5 `ovl_compute` | 8B | 2 | 6040 | 873,6 / 15 260 ms | 44,7 / 69,9 ms |
| T1 `ovl_trace_big` | 8B | 12 | 1275 | 25,1 / 64,3 ms | 10,4 / 24,1 ms |

- Os valores por modelo e a dispersão entre modelos idênticos estão em `reports/data/F02/ded/latencia_ded.md`.
- **Limitação do C5 (`observacoes.md` O2):**
  - Cada 8B recebe ~25 req/s, o que, sozinho numa GPU sem CUDA graphs, está no limite da capacidade. No `model_1`, a fila não se desfez: o TTFT mediano foi de 14,6 s, contra 63 ms no `model_2`.
  - A base é dominada pela fila do próprio modelo, e por isso o S2/S2M é frouxo no TTFT do C5.
  - Ela fica como está, porque o critério é o mesmo para todas as cargas (D21). No C5, a leitura vai pelo S1 e pela vista só TPOT.

### Como entram no SLO

Para uma requisição do modelo `m` na carga `c`:

```
S2:   SLO_TTFT = k_T · pool_ttft_p95(c, m)    SLO_TPOT = k_D · pool_tpot_p95(c, m)
S2M:  SLO_TTFT = k_T · pool_ttft_p50(c, m)    SLO_TPOT = k_D · pool_tpot_p50(c, m)
S3:   SLO_TTFT = k_A · Ĉ_at(m)                SLO_TPOT = k_D · pool_tpot_p95(c, m)
S6:   SLO_TTFT = k_R · Ĉ_rot(m)               SLO_TPOT = k_D · pool_tpot_p95(c, m)
S1D:  SLO_TTFT = ttft (absoluto, 1 s)         SLO_TPOT = k_D · pool_tpot_p95(c, m)
```

- **S1D (D56):** o TPOT do artigo do Prism (§7.1) ao lado do TTFT absoluto do S1. É o padrão das tabelas desde a F6.15: só TPOT com `k_D = 2` (valor do artigo, §7.4: "TPOT SLO scale is 2.0"; Fig. 9b varia de 2,0 a 4,0) e `k_D = 5` (o `k_D` dos níveis S2/S3/S6, D23), e combinado 1 s + 5×P95. Para os 8B: 2×P95 ≈ 45–60 ms, 5×P95 ≈ 113–148 ms (C6 113, T1 120, C1 128, T3 148).
- **Limitação do `k_D = 2` aqui:** sob a sobrecarga dos nossos cenários (10–14 modelos por GPU, sem CUDA graphs, D22), o TPOT servido fica em 51–54 ms no p10 e 73–92 ms na mediana (F6.15, A0.4 e A2.1 no C1/T1); o `k_D = 2` cai abaixo de quase tudo (4–16% atendem) e quase não separa políticas. O `k_D = 5` é a coluna informativa.

- O cálculo é feito por `polyaxon/slo_metrics.py`, que busca a base pela carga (a parte `ovl_*` do caminho do nível) e pelo nome do modelo. Se a base faltar, o script aborta.
- O SLO não depende do tamanho do prompt, como no artigo.
- **Níveis aprovados (D23):**
  - S2: `k_T ∈ {2, 5, 10, 25}`, `k_D ∈ {1,5; 2; 3; 5}`;
  - S2M: `k_T ∈ {5, 10, 25, 50}`, `k_D ∈ {3, 5, 10, 20}`.

Exemplo, C2 (8B):

| | `k_T = 5` | `k_T = 10` | `k_D = 3` | `k_D = 5` |
| --- | --- | --- | --- | --- |
| S2 | 0,62 s | 1,24 s | 78 ms | 130 ms |
| S2M | 0,19 s | 0,37 s | 32 ms | 54 ms |

### Cuidados

- **A base depende da configuração do servidor e do ruído do nó.** Sem CUDA graphs (`observacoes.md` O1, D22), o decode é limitado pela CPU. Se mudar a configuração (CUDA graphs, pool, versão do SGLang ou kvcached), é preciso medir de novo, de preferência sozinho no nó.
- **A base não tem ativação de modelo frio nem disputa entre modelos.** É isso que o `k_T` e o `k_D` medem.
- **Modelos novos não têm base.** Os 14B/32B da F3 (C10) precisam de execuções dedicadas antes de entrar em S2 ou S2M.

### Como reproduzir

```bash
for x in a b c; do   # até 3 jobs simultâneos (D20)
  PRISM_JOB_SUFFIX=-f2-ded-$x PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_ded_${x}_suite.tsv PRISM_TIMEOUT=14400" polyaxon/submit.sh
done
# downloads um de cada vez, conferindo o uuid em environment.txt
polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path /mnt/scratch/scheduler/prism-raw/F2/f2-ded-<x>
R=/mnt/scratch/scheduler/prism-raw/F2
/mnt/scratch/scheduler/opt-env/bin/python polyaxon/iso_dedicated.py reports/data/F02/ded \
  $R/f2-ded-a/outputs $R/f2-ded-b/outputs $R/f2-ded-c/outputs
cp reports/data/F02/ded/latencia_ded.json reports/registro/latencia_ded.json
```

## Sondas sintéticas `TTFT_iso` / `TPOT_iso` (D18; hoje para `p̂` e S2L)

Os valores estão em `reports/registro/latencia_ref.json`, gerado por `polyaxon/iso_fit.py` a partir da rodada `f2-iso2` (job `23d61305`, sozinho no nó).

**Medição:**
- **Servidor:**
  - um único modelo, ativo desde o início;
  - os mesmos flags das cargas, 1 worker e pool de KV de 10 GB;
  - um servidor novo por repetição, 5 repetições;
  - 3 requisições de aquecimento, descartadas.
- **Prompts:** sintéticos `"Hello " × L`, com saída de tamanho exato (`ignore_eos`).
- **`TTFT_iso(m, L)`:**
  - uma requisição por vez, `L ∈ {64, …, 4096}`, 10 por `L`, saída de 4 tokens, 350 pontos;
  - ajuste de reta `a + b·L` por regressão pela mediana (L1).
- **`TPOT_iso(m)`:** um fluxo fechado de 4 requisições por repetição (prompt de 512, saída de 256). O valor é a mediana. É um decode com lote 1.

| Modelo | `TTFT_iso(L)` | erro mediano / p90 (fora da amostra) | `TPOT_iso` | com 8 fluxos | CV do TPOT entre repetições |
| --- | --- | --- | --- | --- | --- |
| Llama-3.1-8B | 19,1 ms + 27,6 µs·L | 10,6% / 32,7% | 12,2 ms | 14,7 ms | 7,8% |
| Llama-3.2-3B | 16,9 ms + 12,5 µs·L | 13,2% / 32,4% | 9,9 ms | 10,0 ms | 8,0% |

S2L (só comparação): `SLO_TTFT = k_T·(a_m + b_m·L_r)`, `SLO_TPOT = k_D·TPOT_iso(m)`.

A mediana dedicada (S2M) e a sonda concordam no TPOT: 9–11 ms contra 12,2 ms. A primeira rodada das sondas, `f2-iso`, rodou junto com outros dois jobs e teve CV de 48%, o mesmo ruído que motivou a D21.

```bash
PRISM_JOB_SUFFIX=-f2-iso2 PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_iso_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh   # sozinho no nó
/mnt/scratch/scheduler/opt-env/bin/python polyaxon/iso_fit.py reports/data/F02/iso2 \
  /mnt/scratch/scheduler/prism-raw/F2/f2-iso2/outputs/iso_8b /mnt/scratch/scheduler/prism-raw/F2/f2-iso2/outputs/iso_3b
cp reports/data/F02/iso2/latencia_ref.json reports/registro/latencia_ref.json
```
