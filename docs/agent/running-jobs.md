# Running experiments

All GPU experiments run on the Kunumi Polyaxon cluster: project `kunumi/hpc4ai`, queue `axia/default`, a single
**8×H200 node shared with other teams**. The local box has 2×RTX 4090, usually busy with other users' jobs, so use
it only for CPU work (tests, analysis). Never kill other users' jobs.

## The rules that affect every submission

- **At most 3 Prism jobs running or queued at once, counting all sessions.** Check before submitting:
  `polyaxon ops ls -p kunumi/hpc4ai -l 30`. Probe jobs (`cluster_probe`) don't count.
- **SGLang only.** Use the default image; never set `PRISM_BACKEND=vllm` or use a vLLM image.
- **Don't re-run because the day changed; reuse existing data (D61).** Read TPOT and SLO together: if TPOT was
  normal, an SLO difference is the policy. TPOT signals drift only for the same config against its own runs,
  node-wide, and ≥ ~10% (CLAUDE.md rule 3); never compare TPOT between policies (they differ by 30–110%). Concurrent, interleaved re-runs with CIs only when Gabriel asks.
- Latency reference runs (`iso_lat`, `PRISM_OVL_DEDICATED`) must run **alone on the node** (D18).
- Think about the job count before a campaign. N reps × M suites at 3 concurrent jobs is the wall time.

## Polyaxon CLI

```bash
PLX=/mnt/scratch/scheduler/polyax-env/bin/polyaxon        # or: cd /mnt/scratch/scheduler && source polyax-env/bin/activate
$PLX ops ls -p kunumi/hpc4ai -l 30                        # status of recent runs (-o json → {"results": [...]})
$PLX ops get -p kunumi/hpc4ai -uid <uuid>
$PLX ops logs -p kunumi/hpc4ai -uid <uuid>                # live run.log
$PLX ops stop -p kunumi/hpc4ai -uid <uuid>                # only your own jobs
```

A run in status "warning" is a pod PENDING for a GPU ("Insufficient nvidia.com/gpu"). The cluster counts
pending time against the job's termination timeout, which `submit.sh` accounts for (see below).
Host: https://sc.kunumi.io. The guide is `polyaxon.pdf`.

## Submitting: `polyaxon/submit.sh`

`polyaxon run -u` would upload the whole cwd, so `submit.sh` stages only `python/`, the benchmark files,
`polyaxon/{run_examples.sh, probes, overload_load.py, iso_latency.py, compare/, configs/}` and the yaml. Then it
fills the placeholders of `prism_examples.yaml` and runs `polyaxon run -p kunumi/hpc4ai -f prism_examples.yaml -u`.

| Variable | Meaning |
| --- | --- |
| `PRISM_JOB_ENV` | Env exported inside the job, e.g. `"PRISM_SUITE=polyaxon/configs/x_suite.tsv PRISM_TIMEOUT=7200"` |
| `PRISM_JOB_SUFFIX` | Run name = `prism-examples<suffix>`. Use the campaign and rep, e.g. `-f2-ded-a`, `-f1-loss-3` |
| `PRISM_IMAGE` | Default `gabrielliman/prism:sglang0.3.4-cu121` |
| `PRISM_GPUS` | GPUs to request (default 1; only `prism2` needs 2) |
| `PRISM_PYTHON_SRC` | Upload another `python/` tree, e.g. `/mnt/scratch/scheduler/prism-base/python` (Prism as published, `c86d528`) or an old commit's worktree for code A/B tests |
| `PRISM_QUEUE_WAIT` | Extra cluster timeout for waiting on a GPU (default 43200 s). Cluster timeout = `PRISM_TIMEOUT` + 1800 + this |

Inside the job, `timeout ${PRISM_TIMEOUT:-5400}` limits the run itself. Give big suites 7200–14400 s.

Examples, taken from the phase reports:

```bash
PRISM_JOB_SUFFIX=-f2-smoke PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_smoke_suite.tsv PRISM_TIMEOUT=5400" polyaxon/submit.sh
for x in a b c; do PRISM_JOB_SUFFIX=-f2-ded-$x PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f2_ded_${x}_suite.tsv PRISM_TIMEOUT=14400" polyaxon/submit.sh; done
PRISM_JOB_SUFFIX=-f1-code-old-1 PRISM_PYTHON_SRC=<worktree>/python PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_codeab_suite.tsv" polyaxon/submit.sh
PRISM_JOB_SUFFIX=-smoke PRISM_JOB_ENV="PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5 PRISM_TIMEOUT=3600" polyaxon/submit.sh   # one step, no suite
```

Always run a **smoke job** (one short level) after changing code or `run_examples.sh` before a campaign.

## What runs in the job: `polyaxon/run_examples.sh`

Per job, it `pip install -e python --no-deps` (your uploaded code), links the HF cache into a private `HF_HOME`,
writes `environment.txt` (host diagnostics, pod name, package versions) and starts Redis. Then, for every
**level**, it runs the health gate (`kvcached_probe.py --parallel 10`; waits on an unhealthy node and skips the
level after `PRISM_HEALTH_WAIT_S`), a fresh server (up to `PRISM_START_ATTEMPTS=3` tries), the load, and
`nvidia-smi` sampling.

### Suites (`PRISM_SUITE`)

A file `polyaxon/configs/<name>_suite.tsv`. `#` lines are comments; every other line is
`<config name><TAB><VAR=value ...>`. The configs run one after another in the same job, so they share the node
and the time window. That is how arms are paired. Results go to `outputs/<config name>/<step>/<level>/`. Name
the Prism-as-published arm `base`, because `collect_reps.py` treats `base*` / `idle50` as the original policy. The
files are gitignored: `git add -f polyaxon/configs/<file>`.

```
# my_suite.tsv — what it tests, which decision/phase
base	PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5
idle5	PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5 PRISM_IDLE_THRESHOLD=5
tp_P0	PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5 PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=3
```

### Steps (`PRISM_STEPS`, space- or comma-separated)

| Step | What |
| --- | --- |
| `static`, `elastic`, `prism1`, `prism2` | The README examples (`prism2` needs `PRISM_GPUS=2`) |
| `overload` | Example 3 with 8 models over budget at `PRISM_TIME_SCALES` |
| **`ovl_mem`** (C1) | 10×8B (6 on), all sending; rates `0.2 0.5`, 300 s |
| **`ovl_phases`** (C2) | 10×8B in 2 groups taking turns every `PRISM_OVL_PHASE`=150 s; rate `0.5`, 600 s |
| **`ovl_mix`** (C3) | 8×8B + 2×3B (`PRISM_OVL_MODEL2`, rate `PRISM_OVL_RATE2`=0.12); rate `0.2`; at most 10 models |
| **`ovl_kv`** (C4) | 4 models that fit, long prompts and outputs; rates `0.25 0.5 1` |
| **`ovl_compute`** (C5) | 2 models, rate beyond decode capacity; rates `5 12.5 25 50` |
| `ovl_trace`, **`ovl_trace_big`** (T1) | Prism's real trace (8 or 12×8B); levels are time scales `ts1`, `ts0.5` |
| `iso_lat` | One model's reference latencies (F2.10). Run alone on the node |
| `kvcached_probe`, `cmp_overhead`, `wp_test`, `switch_static`/`switch_elastic` | Diagnostics |

Default model: `meta-llama/Llama-3.1-8B-Instruct` (`PRISM_OVL_MODEL`). Workload definitions are in
`reports/registro/cargas.md`.

### Main `ovl_*` knobs

`PRISM_OVL_RATES` (levels), `PRISM_OVL_N` / `PRISM_OVL_ON` (models / initially active), `PRISM_OVL_POOL`
(KV GB per model), `PRISM_OVL_DURATION`, `PRISM_OVL_DRAIN` (deadline after the window), `PRISM_OVL_LOAD`
(replaces the load args: lengths, `--cv`, `--groups`), `PRISM_OVL_SLO_TTFT` / `_TPOT` (1.0 / 0.1),
`PRISM_OVL_WORKERS`, `PRISM_OVL_MAX_MEM`, `PRISM_OVL_DEDICATED=all` (each model alone: the S2 base).

Policy knobs: `PRISM_IDLE_THRESHOLD`, `PRISM_SCHEDULE_INTERVAL`, `PRISM_EVICTION` and its knobs
([policies.md](policies.md)). Robustness and diagnostics: `PRISM_MEMORY_ARBITER` (0), `PRISM_DETECT_DEAD_WORKERS` (1),
`PRISM_DETECT_DEAD_MODEL_SERVICE` (1), `PRISM_DECISION_LOG` (on by default in `run_examples.sh`; set it empty to
disable), `PRISM_TRACE_RIDS=1` (worker hops `worker_prefill`, `worker_retract`, `worker_retract_oom`, `worker_inflight_at_deactivate` since P16; `polyaxon/trace_rids.py`), `PRISM_STACK_DUMPS=1` with `PRISM_STACK_DUMP_AT="<s> ..."`, and `PRISM_FAULT`
(`kill`/`kill_model_service`/`ballast` fault injection).

## Downloading results (ONE job at a time)

Keep raw downloads outside git, in `/mnt/scratch/scheduler/prism-raw/<campaign>/<job>/` (not `/tmp`):

```bash
D=/mnt/scratch/scheduler/prism-raw/<campaign>/<job>; mkdir -p "$D"
$PLX ops artifacts -p kunumi/hpc4ai -uid <full uuid> -d outputs --no-untar --path "$D"
cd "$D" && tar -xzf outputs.tar.gz      # the archive has trailing bytes: tar warns but extracts everything
grep plx-operation "$D"/outputs/environment.txt "$D"/environment.txt 2>/dev/null   # must contain the run's uuid
```

Never run downloads in parallel (`xargs -P`, background loops): files from different jobs get mixed. Layout:
`<job>/outputs/{run.log, environment.txt, <config>/<step>/<level>/}`, and a level has `requests.json`,
`summary.json`, `gpu.csv`, `health.log`, `server.log`, `server_file.log*`, `decisions.jsonl`. If tar extracts without
the `outputs/` prefix, move the files under `outputs/` so the scripts below find them. Server log timestamps are
container-local time (UTC−7 in October, UTC−8 from November); `run.log` is UTC.

## Validate, then analyse

```bash
R=/mnt/scratch/scheduler/prism-raw; PY=/mnt/scratch/scheduler/opt-env/bin/python
# 1. validator V1–V15 per level: only VALIDA levels may be used in results
python3 polyaxon/validate_run.py --csv reports/data/<FXX>/validador/<campaign>.csv $R/<campaign>/<job> [...]
# 2. register the runs (reports/registro/execucoes.csv)
python3 polyaxon/register_runs.py reports/data/<FXX>/validador/<campaign>.csv --fase <FXX> --commit <hash>[+diff] --suite polyaxon/configs/<suite>.tsv
# 3. merge clean repetitions into a data dir, then compute metrics
python3 polyaxon/collect_reps.py reports/data/<dest> <round>=$R/<campaign>
$PY polyaxon/summarize_reps.py reports/data/<dest>                    # metricas.csv, resumo.csv
$PY polyaxon/validate_campaign.py reports/data/<dest> <validator.csv> --pair <new>=<ref>
# 4. tables, SLO views, figures
$PY polyaxon/report_tables.py reports/data/<dest>/metricas.csv ovl_phases/rate0.5
$PY polyaxon/slo_metrics.py table reports/data/<dest> <out.csv> --slo S1:ttft=1,tpot=0.1 --slo S2:kT=10,kD=5
$PY polyaxon/slo_curves.py reports/data/<dest> <validator.csv> reports/data/<dest>/curvas
$PY polyaxon/plot_suite.py ...                                         # 3-panel timelines (see its docstring)
```

Write `--commit <hash>+diff` when the job ran uncommitted code, and save the diff under
`reports/data/<FXX>/codigo/`. When a level fails validation, follow the investigation protocol in
`PLANO_AGENTE.md` §0.3 and [pitfalls.md](pitfalls.md) before re-running. Classify a failure as infrastructure only
with external evidence (D11).

## Running locally (CPU work and debugging only)

Mirror `install.md` exactly: container `lmsysorg/sglang:v0.3.4.post2-cu121`, `pip install -e "python[all]"`,
kvcached `prism/shm` from `/mnt/scratch/scheduler/kvcached`, a Redis container, and
`-v /mnt/scratch/global/huggingface_cache/huggingface:/root/.cache/huggingface`. Check `nvidia-smi` first. The
local GPUs are usually taken, so real experiments go to Polyaxon.

## Rebuilding the image

Needed only when SGLang/kvcached install-level dependencies change: `docker/prism/build.sh` (`PUSH=1` pushes
`gabrielliman/prism:sglang0.3.4-cu121`). Ask the user first, since it replaces the image every job pulls
(`imagePullPolicy: Always`). Normal code changes need no rebuild, because each job uploads and reinstalls `python/`.
