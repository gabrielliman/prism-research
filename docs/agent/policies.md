# Scheduling policies: where they live and how to add one

## How the policy is called

`controller_global.py: run_scheduling_loop` runs once per cycle:

1. `handle_model_events()` pops GPU-scheduler events from Redis. On `model_activated` or `model_lost` it calls
   `policy.activation_done(model, gpu)` if the policy has that method. On `model_lost` it marks the instance
   INACTIVE. On `model_service_lost` it stops calling the policy, because no activation can succeed (P12).
2. It deep-copies `model_queues` (`Dict[str, ModelQueueTracker]`) under the lock.
3. It calls `actions = self.policy.gen_actions(model_queues_cpy, self.model_instance_state_dict)`. **Two
   arguments**: `GlobalPolicy` declares a third, `simulated_gpu_queues`, which the controller never passes.
4. It executes the actions (`action.py`), then sleeps for the rest of `PRISM_SCHEDULE_INTERVAL`. When
   `PRISM_IDLE_THRESHOLD` is set, `run_examples.sh` defaults the interval to `min(5, threshold)`.

The policy is built in `controller_global.py` (around line 143):

```python
if self.server_args.policy == "simple-global":
    self.policy = SimpleGlobalPolicy(num_gpus=..., gpu_mem=..., model_weights_info=..., workers_per_gpu=...)
```

and the `--policy` choices are in `multi_model_server_args.py` (around line 908, `choices=["simple-global"]`).

## The current policy: `policy/simple_global.py` (`SimpleGlobalPolicy`)

`gen_actions` runs these steps in order:

| Step | Code | What it does |
| --- | --- | --- |
| 0 | top of `gen_actions` | Precompute: remaining time budgets, violation stats, GPU → active instances, `active_since`; `_update_tput` when `PRISM_EVICTION=throughput`; decision log |
| 1 | `_check_idle_instance_eviction` | Evicts active models with no requests for `MODEL_IDLE_THRESHOLD` s (`PRISM_IDLE_THRESHOLD`, default 50; per model with `adaptive`, see `_idle_threshold`) |
| 2 | `_find_optimal_migrations` (`migrate_policy = "memory_per_request"`) | Migrates models between GPUs. Only matters with more than one GPU; our runs use 1 |
| 3 | `_find_inactive_models_with_requests`, `_place_inactive_model` | Plans activations for inactive models that have requests, if `weights + ACTIVATION_HEADROOM (+ ACTIVATION_KV_GB)` fits in measured free memory minus pending activations (R2.1, `_pending_activation_gb`). A model that doesn't fit is noted `no_fit` and added to `unplaced_models` |
| 3b | `_pressure_evictions` / `_throughput_swaps` | **Alternative eviction strategies** (below): free room for the `unplaced_models` |
| 4–5 | end of `gen_actions` | Emits Deactivate/Activate actions (deactivations sorted first), records pending activations, logs `ACTION:` lines and decision-log entries |

### Strategy knobs (env vars read in `__init__`, around lines 180–230)

| `PRISM_EVICTION` | Behaviour | Knobs |
| --- | --- | --- |
| `idle` (default = Prism as published) | Evicts only after the idle threshold | `PRISM_IDLE_THRESHOLD` |
| `pressure` | Also evicts the LRU model idle for at least `PRESSURE_MIN_IDLE` when an inactive model with requests doesn't fit | `PRISM_PRESSURE_MIN_IDLE` (2), `PRISM_PRESSURE_COOLDOWN` (10) |
| `adaptive` | Per-model threshold = K × p90 of its own inter-arrival gaps; under pressure, evicts the most overdue model | `PRISM_ADAPTIVE_K` (3), `PRISM_ADAPTIVE_MIN` (5) |
| `fair` | `pressure`, plus rotating out the longest-active model when someone has waited `FAIR_QUANTUM` | `PRISM_FAIR_QUANTUM` (30) |
| `throughput` | Swaps by tokens/s per GB, with aged demand, a margin, a minimum residency and a reservation | `PRISM_SWAP_MARGIN` (0.2), `PRISM_SWAP_MIN_RESIDENCY` (20), `PRISM_SWAP_AGING_S` (30), `PRISM_SWAP_PREEMPT` (0/1), `PRISM_SWAP_RESERVATION_END` (`event`: the swap reservation lasts until the incoming model is activated or has no waiting requests, at most `PRISM_SWAP_RESERVATION_MAX_S` = 120 s; `timer`: the pre-D45 fixed 15 s; also used by edf/lvf). The timed drain (`PRISM_SWAP_DRAIN`, `PRISM_SWAP_DRAIN_TIMEOUT`) was removed (D30); setting it raises an error |
| `edf` (A2.1, F6a) | EDF between models: activates by the earliest viable request slack (deadline from the request's SLO, `PRISM_OVL_SLO_SPEC`); rotates busy models only for a later deadline (`policy/deadline.py` `edf_select`) | `PRISM_EDF_FLOOR` (0), `PRISM_EDF_BUDGET` (1 rotation in flight), `PRISM_SWAP_PREEMPT` |
| `lvf` (A9.1, F6a) | SuperInfer's Largest Virtual-lag First between models; an active model scores −(time active), so its victims are the longest active, busy or not (`lvf_select`) | `PRISM_LVF_ALPHA` (3), `PRISM_LVF_BETA_F` (0.5), `PRISM_LVF_BETA_B` (0), `PRISM_LVF_BUDGET` (1), `PRISM_SWAP_PREEMPT` |
| `lvf` + `PRISM_LVF_COST_AWARE=1` (A9.2, F6, 2026-11-09) | Residency-aware lag: the same request lag for active and inactive models plus the measured swap time Ĉ_rot (`reports/registro/c_rot.json`, with/without preemption); rotates m in only if its lag when it could start, G_m, beats the lag its victims' requests take if they leave, K_v (with preemption their running requests restart: α·Ĉ_rot), victims cheapest per GB first (`_lvf_cost_aware`, tests `tests/policy/test_lvf_cost_aware.py`) | `PRISM_LVF_MARGIN` (0), `PRISM_CROT_FILE`, the `lvf` knobs; missing table = error |

Structural constraints A1 (F4, `policy/structural.py`; apply to every strategy, all off by default; D34):
`PRISM_KV_RESERVE_REQS` (A1.1 `b`: activate only with KV for `b` mean-size requests **plus kvcached's 5% floor**,
`PRISM_KV_FLOOR_FRAC`), `PRISM_DEADLOCK_S` (A1.2 `Δ_imp`: no token served for that long while an active model has
waiting requests and nothing is in transition → evict the lowest-value active model with preemption; logged as
`deadlock break for <model>` / decision-log note `deadlock`), `PRISM_MIN_RESIDENCY` (A1.3 `T_min`: no eviction of a
model resident for less). F4 values: `b=4`, `Δ_imp=30`, `T_min=10`. Tests: `tests/policy/test_structural.py`.

Cross-cutting knobs: `PRISM_ACTIVATION_HEADROOM_GB` (default 0; extra GB beyond the weights needed to activate,
which avoids the ovl_mix freeze), `PRISM_ACTIVATION_ACCOUNTING` (default 1 = R2.1; 0 = Prism as published),
`PRISM_SCHEDULE_INTERVAL`.

## Adding a new strategy

Pick the smallest route that fits:

### Route A: a new eviction or swap rule (most common)

It reuses Prism's activation, placement and migration logic and changes only *who leaves the GPU*.

1. In `SimpleGlobalPolicy.__init__`: add the name to the `assert self.EVICTION in [...]` list and read its knobs
   with `os.environ.get("PRISM_<NAME>_...", default)`. Document them in the comment block above `self.EVICTION`.
2. Write `_my_evictions(self, unplaced_models, model_queues, gpu_to_active_instances, idle_instance_keys, ...)`
   that returns a list of `(victim ModelInstanceState, gpu_id, reason str)`. Skip instances already in
   `idle_instance_keys`, and don't evict models that are still activating (`self.pending_activations`).
3. Add a branch in step 3b of `gen_actions` (the `if self.EVICTION == "throughput": ... elif ...` block) and
   set `preempt` for the resulting `DeactivateAction`s. With `preempt=False` the not-yet-started requests go back
   to the model's queue and the running batch finishes without a time limit; with `True` it is recomputed later (D30).
4. Keep the `ACTION: deactivate ... Reason: <reason>` log line and the `self.dlog.action(...)` call.
   `extract_ovl.py` parses those lines into `events.csv` with the regex
   `Reason: (pressure eviction|fair rotation|throughput swap) for <model>` (around line 130). Use the form
   `"<reason> for <waiting model>"` and add your reason to that regex, or your evictions won't appear in the
   timelines.
5. If the rule needs its own state over time (as `throughput` does with `served_history`), update it in step 0.

### Route B: a whole new policy class

Use this for deadline-aware policies (A2–A9 of `PLANO_AGENTE.md`), which change activation order as well.

1. Create `policy/<name>.py` with `class MyPolicy(GlobalPolicy)` implementing
   `gen_actions(self, model_queues, model_instance_state_dict) -> List[BaseAction]`. Subclassing
   `SimpleGlobalPolicy` and overriding parts is often easier and keeps R2.1 accounting and the decision log.
2. Optional: implement `activation_done(model_name, gpu_id)` to receive activation completions.
3. Optional: expose `MODEL_IDLE_THRESHOLD`, because the controller logs it at start-up (`self.policy.MODEL_IDLE_THRESHOLD`).
4. Register it in `controller_global.py` (the `if self.server_args.policy == ...` block) and add the name to
   `--policy` `choices` in `multi_model_server_args.py`.
5. Selecting it: `run_examples.sh` hardcodes `--policy simple-global` in 4 server commands (search for
   `--policy simple-global`). Add a knob there (e.g. `--policy "${PRISM_POLICY:-simple-global}"`) instead of
   editing the default.

### Rules for any new policy

- **The default must stay Prism as published.** A new behaviour is opt-in through an env var, so old suites
  and the `base` arms keep their meaning.
- Keep decision functions pure where possible and put estimates in `estimators.py`, so they can be unit-tested
  on hand-built states (`PLANO_AGENTE.md` §0.4/§0.6). Add tests under `tests/controller/`. `test_decision_log.py`
  shows how to import the policy with SGLang stubbed out.
- Use the estimators instead of constants: Ĉ_at for activation cost, q̂_r for queue time, λ̂ for rates.
  Policies that use the SLO must take it from the request, never from a hardcoded constant.
- To try a strategy: write a suite with a `base` line and your lines, in the same job (same node, same window),
  with ≥3 repetitions. Validate every level before using it ([running-jobs.md](running-jobs.md)).
- Log the change in the change log report and, if it is a design decision, in `reports/registro/decisoes.md`.
