# Testing

## Unit tests (CPU only: no GPU, server or SGLang install)

Use the analysis Python, which has torch, pandas and numpy (system `python3` lacks some of them):

```bash
PY=/mnt/scratch/scheduler/opt-env/bin/python
$PY -m unittest tests/controller/test_decision_log.py      # policy + decision log, SGLang stubbed out (2 tests)
$PY -m unittest tests/controller/test_estimators.py        # estimators.py on hand-built inputs (7 tests)
$PY -m unittest tests/robustness/test_model_service_alive.py  # P12 model-service PID liveness (5 tests)
$PY -m unittest tests/policy/test_deadline.py tests/policy/test_structural.py  # F6a A2.1/A9.1, F4 A1.1-A1.3
KVCACHED_SRC=/mnt/scratch/scheduler/kvcached $PY test/multi-model/test_memory_robustness.py  # from a worktree, or all 8 skip
$PY test/multi-model/test_memory_robustness.py             # memory arbiter + kvcached fixes, simulated device (8 tests)
$PY tests/controller/bench_decision_log.py                 # cost per cycle of the decision log (benchmark, not a test)
```

All of these passed on 2026-11-04. `test_memory_robustness.py` must be run **as a script**: under
`-m unittest` it finds no tests and errors. It loads kvcached's `slab_allocator.py` from `KVCACHED_SRC`
(default `/sgl-workspace/kvcached`, else `../kvcached` next to the repo).

`test/multi-model/test*.py` (other than the robustness test), `test/lang` and `test/srt` are upstream tests. They
need a GPU and a running server, so we don't use them.

### Testing a new policy

`tests/controller/test_decision_log.py::_load_policy_module` shows how to import `simple_global.py` without
`sglang/__init__` (empty packages, stubs for `io_struct`, `sglang.utils` and the GPU memory probe, with a fixed
`FREE_GB`). Build `ModelQueueTracker`s and `ModelInstanceState`s by hand, call `gen_actions`, and assert on the
returned actions. Each decision function of a new policy needs such a test (`PLANO_AGENTE.md` §0.6).

## Before submitting a job

1. Unit tests pass.
2. `bash -n polyaxon/run_examples.sh` if you edited it. Check that the suite file uses **TABs** between name and
   variables, and that it is `git add -f`'d if it should be kept.
3. The default behaviour is unchanged: new knobs are opt-in, and the `base` arm of a suite means Prism as published.
4. `polyaxon ops ls`: fewer than 3 Prism jobs running or queued, across all sessions.
5. After code changes, run a **smoke job** (one short level, e.g. `PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5`)
   and check `run.log` for `server ready` and the `summary` section, `server.log` for tracebacks, and
   `load.log` for `TypeError` (the R2.5 regression check).

## After a job: is the run valid?

Run `polyaxon/validate_run.py` on every level. It checks V1–V15 (server alive, no worker deaths or K1 or OOM,
nothing stuck, sent = served + unserved, consistent TTFT/TPOT, clocks, and more) and classifies the level
VALIDA or not, with a reason. Only VALIDA levels go into results. Campaign-level checks (enough reps, CV,
same-window comparison against the reference) are `validate_campaign.py` (C-V1–C-V3).
