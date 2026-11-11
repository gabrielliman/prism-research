# Prism research: guide for agents

This repo is a fork of **Prism** (multi-LLM serving on shared GPUs, built on **SGLang 0.3.4** and
**kvcached**). We use it to study and change Prism's **global scheduling policy**: when to activate,
evict and swap models on a GPU under memory and compute overload. Experiments run as Polyaxon jobs on a
shared 8×H200 node. Results go into dated reports in `reports/`, written in Portuguese.

Work branch: `scheduling-research` (SGLang only: the vLLM backend was removed). Branch `main` is upstream Prism.
History (2026-11-09): the work branch was `sglang-only` until F3, then `f3-cargas`; `sglang-only` was deleted (all its
commits are in `f3-cargas`) and `f3-cargas` was renamed `scheduling-research`. Older reports still use the old names.

## Hard rules (read before doing anything)

1. **SGLang only.** Do not run vLLM tests or use vLLM images (rule since 2026-10-22).
2. **At most 3 Prism jobs on the node at once**, counting jobs from *every* session. Check
   `polyaxon ops ls` first and queue larger campaigns in waves of 3. With 4 or more jobs, 38–79% of levels
   hit kvcached CUDA VMM driver failures (`cuMemSetAccess`/`cuMemCreate` out of memory), which makes the
   runs invalid. Short `cluster_probe` jobs don't count toward the limit.
3. **Node drift is by hours, not by day (D61).** The node's speed swings in node-wide episodes of a few
   hours: TPOT p50 went +32% to −20% within one F6.15 campaign, with SLO moving ~17 points, at a constant
   3 jobs. Once the time window is held fixed, the date adds nothing (F4, F5, F6.15; analysis in
   `/mnt/scratch/scheduler/analise-deriva-no-2026-11-11/`). So:
   - **Don't re-run a test case just because it's a different day.** A same-day reference is no safer than
     an older one. Reuse existing data.
   - **Read TPOT and SLO together; TPOT is the gauge of the node's speed.** Every 2 h window where SLO fell
     > 4 points had TPOT +10–33% (window correlation −0.80 to −0.96), and windows with TPOT within ±5% had no
     SLO loss. So if TPOT was normal, an SLO difference comes from the policy, not drift: draw the conclusion.
   - **TPOT is a real drift signal only when all three hold:**
     1. It is compared **within the same config** (policy, workload, seed) against that config's own runs.
        Never compare one policy's TPOT with another's: on the same workload they differ by 30–110%.
     2. The shift is **node-wide**: other configs or jobs in the same window moved the same way. One level
        alone may be that run's own scheduling.
     3. It is **≥ ~10%**. Same config in the same window varies ~4%; the drift episodes were +10% to +33%.
     When TPOT shifted under these conditions and SLO moved with it, the comparison is inconclusive.
   - Concurrent, interleaved re-runs with 95% CIs happen only when Gabriel asks for them.
4. **Download Polyaxon artifacts one job at a time.** Parallel `polyaxon ops artifacts` calls mix files
   between jobs. Afterwards, check that the pod uuid in `environment.txt` matches the run.
5. **Git: never push** without the user's explicit OK. Remote `origin` is the public Multi-LLM org repo,
   and `fork` is the user's. Don't commit the user's research work for them unless they ask.
   `*.tsv` and `*.csv` are gitignored, so new suites need `git add -f`.
6. **Follow `install.md` and its container exactly.** Never hand-build environments. The cluster image
   is `gabrielliman/prism:sglang0.3.4-cu121`, built FROM `lmsysorg/sglang:v0.3.4.post2-cu121` by
   `docker/prism/build.sh`.
7. **Reports:** *offer* a report when a big phase ends and write it only after approval. Each report is
   `reports/YYYY-MM-DD <título>.md` in Portuguese, with the date also in the H1. It must name the
   scripts, commands, env vars and run IDs needed to reproduce it.
   Table standard (D56, from F6.15 on): separate TTFT-only SLO columns at 1/2/5 s; TPOT-only columns
   as in the Prism paper, kD × the model's dedicated-GPU P95 TPOT at kD = 2 (the paper's value) and
   kD = 5 (SLO family S1D); the combined SLO TTFT < 1 s and TPOT ≤ 5×P95; and the absolute 100 ms TPOT
   column as a secondary reference. Older phases used 100 ms / 1 s + 100 ms. F6.15+ tables come from
   `polyaxon/f615_compare.py` (`tabela_padrao.md`); older phases have their own `*_report_tables.py`.
   Reports that use S1D/S2/S2M/S3/S6 cite `reports/registro/latencia_ref.md`.
8. **Never relax an acceptance criterion yourself.** The mission plan is `PLANO_AGENTE.md`, tracked in
   `TODO.md`. A phase starts only after the previous phase's gate is APROVADO (by Gabriel, the user).
   Decisions are logged in `reports/registro/decisoes.md`.
9. **Pick the right Python.** Use `/mnt/scratch/scheduler/opt-env/bin/python` for pandas or matplotlib
   scripts and for the unit tests; system `python3` lacks those packages. The Polyaxon CLI is
   `/mnt/scratch/scheduler/polyax-env/bin/polyaxon`.
10. **HF models:** locally, set `HF_HOME=/mnt/scratch/global/huggingface_cache/huggingface`. On the
    cluster, the cache is `/scratch/hpc4ai/hf_cache`; `run_examples.sh` already handles this.

## Where to find things

| Need | Read |
| --- | --- |
| Which file does what (server, controller, GPU scheduler, SGLang changes, tooling) | [docs/agent/code-map.md](docs/agent/code-map.md) |
| Change the policy or add a new scheduling strategy | [docs/agent/policies.md](docs/agent/policies.md) |
| Run experiments: suites, steps, env knobs, Polyaxon submit/monitor/download, analysis | [docs/agent/running-jobs.md](docs/agent/running-jobs.md) |
| Past results: reports, data, figures, raw logs, run registry | [docs/agent/results.md](docs/agent/results.md) |
| Unit tests and pre-submit checks | [docs/agent/testing.md](docs/agent/testing.md) |
| Known failure modes and how to tell infra from code | [docs/agent/pitfalls.md](docs/agent/pitfalls.md) |
| Terms (C1–C5, S1/S2/S2M/S3, K1, T1, P11, P12, R2.x, D-numbers, P1D0...) | [docs/agent/glossary.md](docs/agent/glossary.md) |

## Quick commands

```bash
# unit tests (CPU only, no GPU or server)
PY=/mnt/scratch/scheduler/opt-env/bin/python
$PY -m unittest tests/controller/test_decision_log.py tests/controller/test_estimators.py tests/robustness/test_model_service_alive.py
$PY test/multi-model/test_memory_robustness.py

# submit a suite to Polyaxon (check `polyaxon ops ls` first: max 3 Prism jobs on the node)
PRISM_JOB_SUFFIX=-my-test PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/my_suite.tsv PRISM_TIMEOUT=7200" polyaxon/submit.sh

# download one finished job (sequentially!) and validate it
/mnt/scratch/scheduler/polyax-env/bin/polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path /mnt/scratch/scheduler/prism-raw/<campaign>/<job>
python3 polyaxon/validate_run.py --csv reports/data/<FXX>/validador/<job>.csv /mnt/scratch/scheduler/prism-raw/<campaign>/<job>
```
