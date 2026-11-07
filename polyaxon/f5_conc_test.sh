#!/bin/bash
# D39: does the node still fail with 8 concurrent Prism jobs? (CLAUDE.md rule 2 caps it at 3 since 2026-10-30: with 4
# jobs 38% of levels hit kvcached CUDA VMM driver errors, with 5+ 71-79%.)
# Wave 1: 8 identical jobs at once; wave 2: the same suite with 3 jobs at once, right after (same day, rule 3), as
# the reference for speed. Each job: C1 (ovl_mem 0.2, 10 x 8B) under A0.4 (throughput swap, many activations and
# deactivations = many kvcached map/unmap calls) and A0.1 + A1. Waits until no Prism job is active on the node, and
# resumes the F5 dedicated-base driver at the end (downloads C6/C7/T3, runs T2).
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=reports/data/F05/conc
mkdir -p "$OUT/validador"
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
S=polyaxon/configs/f5_conc_suite.tsv
{
  echo "# D39 concurrency test (polyaxon/f5_conc_test.sh): C1 under A0.4 and A0.1 + A1"
  printf 'A0.4\tPRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0 %s\n' "$A1"
  printf 'A0.1_A1\tPRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_IDLE_THRESHOLD=50 %s\n' "$A1"
} > "$S"
{ echo "# wave of 8"; for i in 1 2 3 4 5 6 7 8; do printf 'f5-conc8-%s\t%s\n' "$i" "$S"; done; } > polyaxon/configs/f5_conc8_queue.tsv
{ echo "# wave of 3"; for i in 1 2 3; do printf 'f5-conc3-%s\t%s\n' "$i" "$S"; done; } > polyaxon/configs/f5_conc3_queue.tsv

active() {
  /mnt/scratch/scheduler/polyax-env/bin/polyaxon ops ls -p kunumi/hpc4ai --limit 60 -o json 2>/dev/null | \
    /mnt/scratch/scheduler/opt-env/bin/python -c "import sys, json; t = sys.stdin.read(); d = json.loads(t[t.index('{'):]); print(sum(r['name'].startswith('prism-examples') and r['status'] not in ('succeeded', 'failed', 'stopped', 'done', 'skipped', 'upstream_failed') for r in d['results']))"
}
until [ "$(active)" = 0 ]; do echo "$(date -u +%T) waiting for the node ($(active) Prism jobs active)"; sleep 300; done
run_wave() {  # queue, max active, state
  F4_QUEUE=$1 F4_MAX_ACTIVE=$2 F4_STATE=$3 F4_RAW=/mnt/scratch/scheduler/prism-raw/F5/conc F4_VAL=$OUT/validador \
    F4_TIMEOUT=7200 /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_driver.py
}
echo "$(date -u +%T) wave of 8"; run_wave polyaxon/configs/f5_conc8_queue.tsv 8 "$OUT/jobs8.tsv"
echo "$(date -u +%T) wave of 3"; run_wave polyaxon/configs/f5_conc3_queue.tsv 3 "$OUT/jobs3.tsv"
echo "$(date -u +%T) resuming the dedicated-base driver"; bash polyaxon/f4_driver_start.sh f5ded
echo "$(date -u +%T) concurrency test done"
