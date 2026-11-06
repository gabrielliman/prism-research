#!/bin/bash
# Submits a Polyaxon job uploading ONLY what it needs (`polyaxon run -u` uploads the whole cwd).
#
# Usage: polyaxon/submit.sh [job]   (default: prism_examples)
#   PRISM_IMAGE      image (default gabrielliman/prism:sglang0.3.4-cu121)
#   PRISM_JOB_ENV    env for the job, e.g. "PRISM_STEPS=static PRISM_TIMEOUT=1800"
#   PRISM_JOB_SUFFIX suffix for the run name
#   PRISM_GPUS       GPUs to request (default 1; prism2 needs 2)
#   PRISM_PYTHON_SRC python/ tree to upload (default this repo's; e.g. a git worktree of the base version)
set -euo pipefail
JOB="${1:-prism_examples}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
POLYAXON="${POLYAXON:-/mnt/scratch/scheduler/polyax-env/bin/polyaxon}"
IMAGE="${PRISM_IMAGE:-gabrielliman/prism:sglang0.3.4-cu121}"

STAGE="$(mktemp -d /tmp/prism-polyaxon-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
PY_SRC="${PRISM_PYTHON_SRC:-$REPO/python}"
rsync -a --exclude __pycache__ --exclude '*.egg-info' "${PY_SRC%/}/" "$STAGE/python/"
mkdir -p "$STAGE/benchmark/multi-model" "$STAGE/polyaxon"
rsync -a "$REPO/benchmark/multi-model/"{benchmark.py,trace.py,utils.py,model_configs,real_trace.pkl,model_lst.yml,model_lst_18.yml} \
  "$STAGE/benchmark/multi-model/"
cp "$HERE/run_examples.sh" "$HERE/cluster_probe.sh" "$HERE/cluster_probe.py" "$HERE/overload_load.py" "$HERE/workloads.py" "$HERE/slo_metrics.py" "$HERE/iso_latency.py" "$HERE/kvcached_probe.py" "$HERE/test_switching.py" "$HERE/test_worker_pool.py" "$HERE/hf_download.sh" "$STAGE/polyaxon/"
rsync -a "$HERE/compare" "$STAGE/polyaxon/"
rsync -a "$HERE/configs" "$STAGE/polyaxon/"
# F3: normalized traces and length tables (polyaxon/trace_adapt.py). T2 (LMSYS, no redistribution) stays out of the repo.
[ -d "$HERE/traces" ] && rsync -a --include '*.csv.gz' --exclude '*' "$HERE/traces/" "$STAGE/polyaxon/traces/"
# SLO bases for overload_load.py --slo-spec (F6a.1, slo_metrics.py reads them at these paths)
mkdir -p "$STAGE/reports/registro" "$STAGE/reports/data/F02/cat"
cp "$REPO/reports/registro/"{latencia_ded.json,latencia_ref.json,c_rot.json} "$STAGE/reports/registro/"
cp "$REPO/reports/data/F02/cat/cat_model.json" "$STAGE/reports/data/F02/cat/"
cp "$HERE/$JOB.yaml" "$STAGE/"

sed -i "s|__IMAGE__|$IMAGE|; s|__ENV__|${PRISM_JOB_ENV:-}|; s|__SUFFIX__|${PRISM_JOB_SUFFIX:-}|; s|__GPUS__|${PRISM_GPUS:-1}|g" "$STAGE/$JOB.yaml"
# Cluster timeout = the job's PRISM_TIMEOUT (default 5400 s) + 30 min for cleanup + PRISM_QUEUE_WAIT (default
# 12 h): the cluster counts the time a job waits for a GPU ("warning: Insufficient nvidia.com/gpu") against it.
# The run itself is still limited to PRISM_TIMEOUT by the `timeout` inside the container.
JOB_TIMEOUT=$(echo "${PRISM_JOB_ENV:-}" | grep -o "PRISM_TIMEOUT=[0-9]*" | cut -d= -f2 || true)
sed -i "s|__PLX_TIMEOUT__|$(( ${JOB_TIMEOUT:-5400} + 1800 + ${PRISM_QUEUE_WAIT:-43200} ))|" "$STAGE/$JOB.yaml"
echo "python: $PY_SRC | image: $IMAGE | gpus: ${PRISM_GPUS:-1} | env: ${PRISM_JOB_ENV:-(none)} | uploading $(du -sh "$STAGE" | cut -f1)"
cd "$STAGE" && "$POLYAXON" run -p kunumi/hpc4ai -f "$JOB".yaml -u
