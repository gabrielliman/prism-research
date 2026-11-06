# Code map

Paths are relative to the repo root. Prism is SGLang 0.3.4 plus a multi-model layer. Most of our research
changes are in `python/sglang/multi_model/scheduling/` (the policy) and in `polyaxon/` (experiment tooling).

## Request and control flow

```
client (overload_load.py / benchmark.py)
   │ HTTP
   ▼
multi_model_server.py ─ endpoint.py / request_handler*.py   frontend: receives requests, pushes them to Redis queues
   │                                                         (Redis runs inside the job: run_examples.sh starts it)
   ├─ scheduling/controller_global.py   GLOBAL controller: every PRISM_SCHEDULE_INTERVAL s (default 5) copies the
   │     │                              model queues, calls policy.gen_actions(), executes the returned actions
   │     └─ scheduling/policy/simple_global.py   THE POLICY (activate / evict / swap / migrate decisions)
   │
   ├─ scheduling/gpu/gpu_scheduler.py   one per GPU (LOCAL scheduler): applies activate/deactivate, routes requests
   │     ├─ gpu/worker_pool.py          pre-initialized SGLang engines (workers) reused across models
   │     ├─ gpu/request_queue.py, gpu/resource_manager.py
   │     └─ sends events back to the controller over Redis (model_activated, model_lost, model_service_lost)
   │
   ├─ model_sevice.py (sic)             model service: holds weights in CPU shared memory, copies them to the GPU on
   │                                    activation (one model at a time; activations take 1–20 s)
   └─ SGLang engines (python/sglang/srt/…) with kvcached elastic KV memory
```

## `python/sglang/multi_model/`: the Prism layer

| File | Role |
| --- | --- |
| `multi_model_server.py`, `multi_model_server_args.py` | Entry point (`python -m sglang.launch_multi_model_server`) and all CLI flags (`--policy`, `--enable-controller`, `--enable-worker-pool`, `--workers-per-gpu`, `--enable-elastic-memory`, `--use-kvcached-v0`, …) |
| `endpoint.py`, `request_handler.py`, `request_handler_worker_pool.py` | HTTP frontend and request routing. `PRISM_TRACE_RIDS=1` logs every request hop by rid |
| `engine.py` | Multi-model engine coordination |
| `model_sevice.py` | Model service (weights in shared memory). `PRISM_DETECT_DEAD_MODEL_SERVICE` (P12 fix) |
| `memory_arbiter.py` | Per-GPU memory arbiter, worker and model-service PID registry. The arbiter is **off by default** (`PRISM_MEMORY_ARBITER=0`, decisions D5 and 2026-10-22) because it changes how memory is shared; the PID registry is always on |
| `kvcached_patches.py` | Runtime kvcached fixes, active only with the arbiter on. The kvcached repo itself is never modified |
| `stack_dump.py` | `PRISM_STACK_DUMPS=1`: Python stacks of all workers on SIGUSR1 (used to diagnose freezes) |

### `scheduling/`

| File | Role |
| --- | --- |
| `controller_global.py` | Global controller. Builds the policy (`--policy simple-global` → `SimpleGlobalPolicy`, around line 143), runs `run_scheduling_loop`, executes actions, and handles GPU scheduler events (`handle_model_events`: `model_lost`, `model_activated`, `model_service_lost`) |
| `policy/base.py`, `policy/base_global.py` | Abstract `BasePolicy` / `GlobalPolicy` with `gen_actions(...)` |
| `policy/simple_global.py` | **The only policy.** Prism's original algorithm plus our eviction strategies (`PRISM_EVICTION`). See [policies.md](policies.md) |
| `action.py` | `ActivateAction`, `DeactivateAction` (preempt), `ResizeAction`: what a policy returns |
| `state.py` | `ModelInstanceState`, `ModelState` (ACTIVE / INACTIVE / ACTIVATING / DEACTIVATING) |
| `model_queue_tracker.py` | Per-model queue (`waiting_reqs`, running, `served_tokens`, last arrival/finish): the policy's input |
| `estimators.py` | Pure estimators for the deadline-aware policies (F2): activation cost Ĉ_at, prefill p̂, queue q̂_r, rate λ̂. Coefficients in `reports/data/F02/cat/cat_model.json` and `reports/registro/latencia_ref.json` |
| `decision_log.py` | `PRISM_DECISION_LOG=<path>`: one JSON line per cycle (GPU free/pending memory, per-model state, actions, notes). `run_examples.sh` turns it on by default (`<level>/decisions.jsonl`) |
| `stats.py`, `constants.py` | Helpers |
| `gpu/gpu_scheduler.py` | Local scheduler: dead-worker detection (`PRISM_DETECT_DEAD_WORKERS`, default 1), stale-deactivation guard (R2.3), `_on_model_lost` |

## `python/sglang/srt/`: SGLang files Prism changed

`managers/scheduler.py` (worker loop, activate/deactivate handling (preempt or finish the running batch, D30), R2.2 `PrefillKVFull` retry, R2.5 TTFT
fix in `process_batch_result_prefill`), `managers/tp_worker*.py`, `model_executor/worker_pool_model_runner.py`
(weight reservation, activation rollback → `ActivationOutOfMemory`), `model_executor/model_runner.py`,
`single_model_runner.py`, `mem_cache/memory_pool.py` (kvcached elastic pool), `server_args.py`, `utils.py`.
**Only change SGLang with the user's explicit approval.** Every such change is logged as an R-number in the change
log (`reports/2026-10-22 Correções de robustez de memória no Prism (SGLang).md`).

## Benchmarks and workloads

| Path | Role |
| --- | --- |
| `benchmark/multi-model/benchmark.py`, `trace.py` | Upstream Prism benchmark client and trace generation. `overload_load.py` reuses its `send_generate_request` |
| `benchmark/multi-model/real_trace.pkl` | Prism's real e2e trace (used by `ovl_trace`, `ovl_trace_big`) |
| `benchmark/multi-model/model_configs/*.json` | README example server configs (`1_gpu_2_model_*`, `8_gpu_18_model_our.json`). The `ovl_*` steps generate their own config |
| `polyaxon/overload_load.py` | **Our load generator** for the `ovl_*` scenarios: open loop, deadline = duration + drain; unserved requests are recorded |

## `polyaxon/`: experiment tooling (run on the cluster or locally)

| Path | Role |
| --- | --- |
| `submit.sh` | Stages a minimal upload and runs `polyaxon run`. See [running-jobs.md](running-jobs.md) |
| `prism_examples.yaml` | Job template (queue `axia/default`, placeholders filled by `submit.sh`) |
| `run_examples.sh` | What runs inside the job: Redis, HF cache links, health gate, steps (`static`, `elastic`, `prism1/2`, `overload`, `ovl_*`, `iso_lat`, `kvcached_probe`, …), suites (`PRISM_SUITE`) |
| `configs/*_suite.tsv` | Suites: one configuration per line, `name<TAB>VAR=value ...` (gitignored: `git add -f`) |
| `cluster_probe.{sh,py,yaml}`, `kvcached_probe.py` | Node health probes (`kvcached_probe.py --parallel 10` is the health gate) |
| `extract_ovl.py` | Raw level → compact `summary.json`, `requests.csv`, `gpu.csv`, `events.csv` |
| `validate_run.py`, `validate_campaign.py`, `register_runs.py` | Run validator V1–V15, campaign checks C-V1–C-V3, run registry |
| `collect_reps.py`, `summarize_reps.py`, `report_tables.py`, `compare_reference.py` | Merge clean reps → `metricas.csv`/`resumo.csv` → Markdown tables; reproduction checks |
| `slo_metrics.py`, `slo_curves.py`, `iso_dedicated.py`, `iso_latency.py`, `iso_fit.py` | Parametric SLOs (S1/S2/S2M/S3), SLO curves, latency bases |
| `ovl_plots.py`, `plot_suite.py`, `plot_reps.py`, `plot_limits.py`, `plot_cluster.py` | Figures; `plot_suite.py` draws the 3-panel timeline (GPU memory / controller free memory / per-model swimlane) |
| `activation_cost.py`, `estimators_eval.py`, `overhead.py`, `workload_stats.py`, `classify_errors.py`, `trace_rids.py`, `stack_summary.py`, `cluster_history.py` | Specific analyses. Each file's docstring gives its usage |

## Other top-level paths

| Path | Role |
| --- | --- |
| `PLANO_AGENTE.md`, `TODO.md` | Mission plan (phases F0–F11, algorithms A0–A9, workloads, metrics) and its checklist |
| `install.md`, `docker/prism/` | Install steps and the cluster image build (`build.sh`, `PUSH=1` to push) |
| `reports/` | Results. See [results.md](results.md) |
| `tests/controller/`, `tests/robustness/`, `test/multi-model/` | Our unit tests. See [testing.md](testing.md). `test/lang`, `test/srt` are upstream SGLang tests |
| `Prism.pdf`, `SuperInfer.pdf`, `polyaxon.pdf` | Prism paper, SuperInfer paper (Virtual Lag Time, A9), Polyaxon cluster guide |
| `docs/en/` | Upstream SGLang docs (not about Prism) |
| `scripts/`, `examples/`, `experiments/` | Upstream leftovers (manual activate/deactivate scripts, SGLang examples) |

External: kvcached (branch `prism/shm`) is at `/mnt/scratch/scheduler/kvcached`. `/mnt/scratch/scheduler/prism-base`
is a git worktree at `c86d528` (Prism as published), uploaded with `PRISM_PYTHON_SRC` for base-vs-fixed runs.
