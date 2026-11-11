# Glossary

The reports are in Portuguese. Common words: *sobrecarga* = overload, *ociosidade* = idleness, *troca* = swap,
*despejo* = eviction, *estadia/residência* = residency, *folga* = slack, *prazo* = deadline, *nível* = load level,
*carga* = workload, *repetição* = repetition, *atendida* = served, *perdida/sem resposta* = lost/unserved,
*travamento* = freeze, *gate APROVADO / REPROVADO / AGUARDANDO REVISÃO* = phase gate approved / rejected / awaiting review.

## System

| Term | Meaning |
| --- | --- |
| **Prism** | Multi-LLM serving on shared GPUs (paper `Prism.pdf`, arXiv 2505.04021): global controller + per-GPU scheduler + worker pool + kvcached |
| **kvcached** | Elastic KV-cache memory via CUDA virtual memory (VMM): pages are mapped on demand. Branch `prism/shm` |
| **Global controller / policy** | `controller_global.py` / `SimpleGlobalPolicy`: decides activations, evictions, swaps and migrations every cycle |
| **GPU scheduler (local)** | `gpu/gpu_scheduler.py`: executes actions on one GPU, routes requests, detects dead workers |
| **Worker / worker pool** | Pre-initialized SGLang engine processes reused for whichever model is activated (`--workers-per-gpu`) |
| **Model service** | Process that keeps weights in CPU shared memory and copies them to the GPU on activation, one model at a time |
| **Activation / deactivation (eviction)** | Loading a model's weights onto a worker / releasing them |
| **Idle threshold** | Seconds without requests before the original policy evicts a model (default 50, `PRISM_IDLE_THRESHOLD`) |
| **Pool** | Per-model KV memory cap in GB (`max_memory_pool_size`, `PRISM_OVL_POOL`) |
| **Level** | One load point in a step (`rate0.5`, `ts1`, `<level>_ded_<model>`): one fresh server, one directory |
| **Suite / config line** | A `polyaxon/configs/*_suite.tsv` file / one named configuration in it |
| **base / original / idle50** | Prism's published policy (`PRISM_EVICTION=idle`, threshold 50) |
| **tp_PxDy** | Throughput swap with preempt x (0/1) and drain y (0/1), e.g. `tp_P0D1`. Drain (D1) was removed on 2026-11-05 (D30); only P0/P1 remain, and old D1 runs are not comparable with new ones |

## Workloads (`reports/registro/cargas.md`)

| ID | Step | Pressure |
| --- | --- | --- |
| C1 | `ovl_mem` | Weights exceed the GPU, every model always sending: starvation without idleness |
| C2 | `ovl_phases` | 2 groups taking turns: time sharing |
| C3 | `ovl_mix` | 8B + 3B models: different throughput per GB |
| C4 | `ovl_kv` | Models fit, but KV demand doesn't |
| C5 | `ovl_compute` | 2 models, compute saturated |
| T1 (workload) | `ovl_trace_big` | 12×8B on Prism's real trace. Not to be confused with the T1 freeze error |

## Metrics and SLOs (`PLANO_AGENTE.md` §5.4, §7; `slo_metrics.py`)

| Term | Meaning |
| --- | --- |
| TTFT / TPOT | Time to first token / time per output token (server timestamps) |
| Combined SLO | Up to F6.16: TTFT < 1 s **and** TPOT < 100 ms. From F6.15 on (D56): TTFT < 1 s **and** TPOT ≤ 5 × the model's dedicated P95 TPOT (S1D kD=5). Always a fraction of **all sent** requests (unserved = miss), shown with the TTFT-only and TPOT-only views |
| S1 | Absolute SLO, the same for every request (default 1 s / 100 ms) |
| S1D | Absolute TTFT with the Prism paper's TPOT SLO: kD × the model's dedicated-GPU P95 TPOT (§7.1; the paper's "TPOT SLO scale" is 2.0–4.0). Report standard since D56 (kD 2 and 5) |
| S2 / S2M | Relative SLO: k_T × TTFT_base, k_D × TPOT_base, where the base is the P95 (S2) or P50 (S2M) of the model's own workload on a dedicated GPU, pooled over identical models (D20, D21; `latencia_ded.json`) |
| S3 | TTFT relative to the activation cost (k_A × Ĉ_at) |
| S6 / S6P | TTFT relative to the real rotation time (k_R × Ĉ_rot): S6 = victim finishes its batch (no preemption, 8B 15.7 s), S6P = victim preempted (8B 6.4 s); D42 |
| S2L | Older S2 from single-request probes (comparison only) |
| Worst wait | Longest wait for a model's first token in a level |
| ρ_mem | Memory intensity Σ weights / GPU memory |
| Ĉ_at, p̂, q̂_r, λ̂ | Estimators of activation cost, prefill time, queue time and arrival rate (`estimators.py`) |
| V1–V15, C-V1–C-V3 | Per-run validator checks / campaign checks (`PLANO_AGENTE.md` §3) |
| VALIDA / INVALIDA_INFRA | Validator classification. Only VALIDA levels count |

## IDs used across reports

| Prefix | Meaning | Where defined |
| --- | --- | --- |
| F0–F15 | Mission phases. Execution order (D58): F0, F1, F2, F6a, F3, F4, F5, F6, F14 (heterogeneous models, size- and activation-aware policies), then F12 (swap cost), F13 (candidate policy), F15 (generalization), F8, F10, F11 (order after F14 revisited at its gate); F7 and F9 were cut | `PLANO_AGENTE.md` §2, §6, `TODO.md` |
| H-unif, H-G-α, H-P-α, H-real | Heterogeneous-model workloads of F14 (size mix from the Prism paper Table 3): uniform popularity; power-law α ∈ {0.9, 2.1} with large models popular (G) or small models popular (P); real popularity × size from LMSYS-Chat-1M (D58) | `PLANO_AGENTE.md` §5.3 |
| A14 | Size- and activation-time-aware adaptations of the best policies (F14, D58) | `PLANO_AGENTE.md` §4.2 |
| A0–A14 | Policy families (A0 baselines, A1 structural constraints, A2 least slack, A3 expected-loss eviction, A9 SuperInfer's Virtual Lag Time (A9.2 residence-aware, A9.4 per-swap preemption), A10 value swap, A11 cancel deactivation, A12 throughput swap with fairness guarantee (candidate, F13), A13 swap-cost reduction mechanisms (F12), A14 size- and activation-aware adaptations (F14); A6 Moore-Hodgson and A8 offline oracle were cut in D55; request refusal (old A5) removed from the plan in D57) | `PLANO_AGENTE.md` §4 |
| D1, D2, … | Decisions | `reports/registro/decisoes.md` |
| R2.1–R2.5 | Round-2 fixes (accounting, prefill/worker exit, race, infra health gate, TTFT fix) | change log report |
| K1 | kvcached `abort()` on a driver OOM, which kills the worker | `reports/erros.md`, limits report |
| S1–S4 (errors) | SGLang errors: pretty_print, server-wide crash, torch OOM, empty finish / overwritten TTFT. Not the same as the S1/S2 SLO families | limits report, `erros.md` |
| P1–P12 | Prism problems from the F0 inventory (P11 slow release, P12 model-service death, …) | `reports/fases/F00_inventario.md`, `erros.md` |
| T1 (error), F5 | Memory deadlock freeze; 14-worker start-up failure | `erros.md` |
