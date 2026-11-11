# Known pitfalls

Full history: `reports/erros.md` (each error, its cause, how it was handled, status) and the change log
`reports/2026-10-22 Correções de robustez de memória no Prism (SGLang).md`.

## Cluster and infrastructure

| Symptom | Cause | What to do |
| --- | --- | --- |
| `cuMemSetAccess`/`cuMemCreate ... out of memory` (K1) at start-up or under load, even on an empty GPU, in several jobs in the same second | Too many Prism jobs on the single shared node (38% of levels with 4 jobs, 71–79% with 5 or more), or a degraded node window | ≤3 Prism jobs at once. Check the same time window across all concurrent jobs before blaming the code. Mark the level invalid (D6, D11) and re-run it |
| K1 in most levels with only 3 jobs, all with many models (F5, 2026-11-07: 10 + 14 + 19 = 43 kvcached workers on the node) | Total kvcached workers on the node, not only the job count (hypothesis, D47) | Driver worker budget `F4_MAX_WORKERS=36`; re-run the whole job. Per-process memory-map counts (vs `vm.max_map_count` 65530 in the containers) are in each level's `map_trace.log` (every 15 s and at a kvcached start-up failure; `PRISM_MAP_TRACE=0` turns it off) |
| The same config gives an SLO 7–17 points different in another run | Node-wide speed episodes lasting hours (TPOT ±20–30%, no known cause), not a per-day effect | Read TPOT and SLO together. TPOT is a drift signal only for the same config against its own runs, node-wide (other configs in the window moved too), and ≥ ~10%. Normal TPOT → the SLO difference is the policy (D61) |
| Job "warning" for hours, then "stopped" with empty outputs | Pod PENDING for a GPU; pending time counts against the termination timeout | `submit.sh` adds `PRISM_QUEUE_WAIT` (12 h). Don't over-queue |
| Downloaded folders contain another job's files | Parallel `polyaxon ops artifacts` | Download sequentially; check the `plx-operation-<uuid>` in `environment.txt` |
| `tar` warns about trailing garbage | The Polyaxon archive format | Harmless: everything is extracted |
| Server log times are off by 7–8 h from `run.log` | Server logs use container-local time (UTC−7 in Oct, UTC−8 from Nov); `run.log` uses UTC | Convert before aligning events |
| "context has already been set" at start-up | transformers' cache migration in a shared HF cache | Already handled by `run_examples.sh` (private `HF_HOME` of symlinks + `version.txt`) |
| Gated base models missing on the cluster | The cluster HF cache has only some models | Configs use the cached Instruct variants. List: `/scratch/hpc4ai/hf_cache/hub`. Use HF ids, not paths, with `HF_HUB_OFFLINE=1` |

## Prism and SGLang behaviour (not infra)

| Symptom | Cause | Status |
| --- | --- | --- |
| **T1 freeze**: GPU full of weights, all workers idle, utilization 0, nothing served (ovl_mem with 8 or 14 models, ovl_mix with the original policy) | A memory deadlock from the policy: activation checks only the weights, so KV has no pages; every model has a queue, so none goes idle and nothing is evicted. kvcached also keeps 5% of the GPU out of the KV pool | Open, assigned to F4 (A1.1 KV reservation, A1.2 deadlock detector). Workaround: `PRISM_ACTIVATION_HEADROOM_GB=3` |
| Requests lost with throughput swap P1D0 | Long requests preempted 3+ times restart from the prompt each time (unbounded recompute) | A policy effect, not a bug; F4 (A1.3 hysteresis) and F6 (A3) |
| P11: deactivation takes 7–88 s, and the whole GPU stalls meanwhile | kvcached `trim()` → `unmap_from_kv_tensors` (sometimes `torch.cuda.empty_cache()`) | Not fixed (kvcached is not modified); modeled as a deactivation-cost distribution |
| P12: model service dies (CUDA OOM rebuilding a shared tensor), so every activation times out after 300 s | — | Fixed (`PRISM_DETECT_DEAD_MODEL_SERVICE=1`): the controller stops activating and evicting and keeps active models serving |
| Activate/deactivate race: a model is starved after re-activation | A late `deact_ok` arrived after the newer activation | Fixed (R2.3, `stale_deact` events) |
| Double-counted free memory, which killed workers during activation | The controller didn't subtract pending activations | Fixed (R2.1, `PRISM_ACTIVATION_ACCOUNTING=1`) |
| `pretty_print` `NotImplementedError` (S1) / one worker exception kills the whole server (S2) | KV full in prefill with radix cache off / `kill_parent_process` | Fixed in SGLang (R2.2) |
| Served request counted as failed, TTFT overwritten (S4) | Prefill after a decode retract | Fixed in SGLang (R2.5); check `load.log` for `TypeError` |
| 14 workers hang at start-up (F5) | kvcached at start-up, depends on node state | Not reproduced lately; keep `ovl_mix` ≤ 10 models |
| `PRISM_MEMORY_ARBITER=1` runs are slower | Lock taken on every `available_size()` (up to 16% of worker time) | Arbiter off by default (D5) |

## Repo and tooling

- `*.tsv` and `*.csv` are gitignored: suites and registries need `git add -f`.
- The model service file is spelled `model_sevice.py`.
- `GlobalPolicy.gen_actions` declares 3 parameters, but the controller passes 2.
- `run_examples.sh` hardcodes `--policy simple-global`, and `--policy` accepts only that value. See
  [policies.md](policies.md) before adding a policy.
- `run_examples.sh` writes the decision log by default. `PRISM_DECISION_LOG=` (empty) turns it off (cost ≈ 0.002%).
- Don't change SGLang (`python/sglang/srt/`) or kvcached without the user's explicit OK. Fix kvcached issues at
  run time from Prism.
- An "infra" classification needs external evidence: a degraded window seen in concurrent jobs, or the health
  probe (D11). Follow `PLANO_AGENTE.md` §0.3 to investigate a failed run.
- `PRISM_CHUNKED_PREFILL_SIZE` (stress tests only) must be at least the load's `--max-prompt` (4096 in the `ovl_*`
  steps): smaller chunks trip SGLang 0.3.4's `assert self.current_inflight_req is None` on fresh workers (P16 work,
  `f6-p16-3`). Never seen with the default 8192.
- Requests "running" on an `INACTIVE` model in `decisions.jsonl` (its `running_rids` field lists them): with
  preemption before R2.6 this was P16 (a request dropped mid chunked prefill, then answered by the wrong model);
  in jobs with K1 or dead workers it is the dead workers' requests. Check worker deaths before blaming a policy.
