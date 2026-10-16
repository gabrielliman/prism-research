#!/bin/bash
# Submits a Polyaxon job uploading ONLY what it needs (`polyaxon run -u` uploads the whole cwd).
#
# Usage: polyaxon/submit.sh [job]   (default: prism_examples)
#   PRISM_IMAGE      image (default gabrielliman/prism:sglang0.3.4-cu121)
#   PRISM_JOB_ENV    env for the job, e.g. "PRISM_STEPS=static PRISM_TIMEOUT=1800"
#   PRISM_JOB_SUFFIX suffix for the run name
#   PRISM_GPUS       GPUs to request (default 1; prism2 needs 2)
set -euo pipefail
JOB="${1:-prism_examples}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
POLYAXON="${POLYAXON:-/mnt/scratch/scheduler/polyax-env/bin/polyaxon}"
IMAGE="${PRISM_IMAGE:-gabrielliman/prism:sglang0.3.4-cu121}"

STAGE="$(mktemp -d /tmp/prism-polyaxon-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
rsync -a --exclude __pycache__ --exclude '*.egg-info' "$REPO/python" "$STAGE"/
mkdir -p "$STAGE/benchmark/multi-model" "$STAGE/polyaxon"
rsync -a "$REPO/benchmark/multi-model/"{benchmark.py,trace.py,utils.py,model_configs,real_trace.pkl,model_lst.yml,model_lst_18.yml} \
  "$STAGE/benchmark/multi-model/"
cp "$HERE/run_examples.sh" "$HERE/test_switching.py" "$HERE/test_worker_pool.py" "$HERE/test_worker_pool_tp.py" "$STAGE/polyaxon/"
rsync -a "$HERE/compare" "$HERE/experiments" "$STAGE/polyaxon/"
rsync -a "$HERE/configs" "$STAGE/polyaxon/"
cp "$HERE/$JOB.yaml" "$STAGE/"

sed -i "s|__IMAGE__|$IMAGE|; s|__ENV__|${PRISM_JOB_ENV:-}|; s|__SUFFIX__|${PRISM_JOB_SUFFIX:-}|; s|__GPUS__|${PRISM_GPUS:-1}|g" "$STAGE/$JOB.yaml"
# Cluster timeout = the job's PRISM_TIMEOUT (default 5400 s) + 30 min for cleanup.
JOB_TIMEOUT=$(echo "${PRISM_JOB_ENV:-}" | grep -o "PRISM_TIMEOUT=[0-9]*" | cut -d= -f2 || true)
sed -i "s|__PLX_TIMEOUT__|$(( ${JOB_TIMEOUT:-5400} + 1800 ))|" "$STAGE/$JOB.yaml"
echo "image: $IMAGE | gpus: ${PRISM_GPUS:-1} | env: ${PRISM_JOB_ENV:-(none)} | uploading $(du -sh "$STAGE" | cut -f1)"
cd "$STAGE" && "$POLYAXON" run -p kunumi/hpc4ai -f "$JOB".yaml -u
