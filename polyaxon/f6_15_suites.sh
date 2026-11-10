#!/bin/bash
# F6.15 confirmation suites (D52, D54): 5 repetitions, objective = fairness between models without big SLO loss.
# One job = one workload x one repetition, all arms in the same window (rule 3), all with A1 (D38), no global preemption.
#   A0.2_A1          idle threshold 10 s + A1
#   A0.4             throughput swap, no preemption, headroom 0 + A1
#   lvfr_<lv>_p0     A9.2 residency-aware VLT, no preemption
#   edf_<lv>_p0      A2.1 EDF between models, no preemption
#   lvfp_<lv>_ps     A9.4 = A9.2 deciding preemption per swap, lambda = 1 (preempt iff saved >= lost; D54)
#   edf_S6k4_p1      A2.1 with preemption, only at S6 kR=4 (D52: best there in F6.0)
# Levels: S3k5 (S3 kA=5, ~7 s for an 8B), S6k1, S6k2, S6k4 (1, 2, 4 real swaps without preemption: ~16, ~31, ~63 s;
# S6 kR=2 added by Gabriel, D54); the deadline is sent per request (PRISM_OVL_SLO_SPEC; kD = 5 only in the metrics).
# Order: units = baselines and (policy, level) arms; the unit order rotates by 4 per repetition.
# Writes polyaxon/configs/f615_<W>_o<rep>_suite.tsv and the driver queue polyaxon/configs/f615_queue.tsv (rep 1 of every
# workload, then rep 2, ...).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPS=${F615_REPS:-5}
WORKLOADS=(${F615_WORKLOADS:-C1n10 T1 C6n14 T3})
LEVELS=(${F615_LEVELS:-S3k5 S6k1 S6k2 S6k4})
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
declare -A W=(
  [C1n10]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2"
  [T1]="PRISM_STEPS=ovl_trace_big PRISM_OVL_RATES=1"
  [C6n14]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2 PRISM_OVL_N=14"
  [T3]="PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1"
)
declare -A BASE=(
  [A0.2_A1]="PRISM_IDLE_THRESHOLD=10 $A1"
  [A0.4]="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0 $A1"
)
declare -A POL=(
  [lvfr]="PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_SWAP_PREEMPT=0"
  [edf]="PRISM_EVICTION=edf PRISM_SWAP_PREEMPT=0"
  [lvfp]="PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_LVF_PREEMPT=per_swap PRISM_LVF_PREEMPT_LAMBDA=1 PRISM_SWAP_PREEMPT=0"
  [edfp]="PRISM_EVICTION=edf PRISM_SWAP_PREEMPT=1"
)
declare -A TAG=([lvfr]=p0 [edf]=p0 [lvfp]=ps [edfp]=p1)
declare -A SLO=([S3k5]="S3:kA=5,kD=5" [S6k1]="S6:kR=1,kD=5" [S6k2]="S6:kR=2,kD=5" [S6k4]="S6:kR=4,kD=5")
UNITS=(A0.2_A1 A0.4)
for lv in "${LEVELS[@]}"; do for p in lvfr edf lvfp; do UNITS+=("$p:$lv"); done; done
UNITS+=("edfp:S6k4")
arm() {  # name<TAB>vars
  local w=$1 u=$2
  if [ -n "${BASE[$u]:-}" ]; then
    printf '%s\t%s %s\n' "$u" "${W[$w]}" "${BASE[$u]}"
  else
    local p=${u%%:*} lv=${u#*:} name
    name="$([ "$p" = edfp ] && echo edf || echo "$p")_${lv}_${TAG[$p]}"
    printf '%s\t%s %s PRISM_ACTIVATION_HEADROOM_GB=0 %s PRISM_OVL_SLO_SPEC=%s\n' "$name" "${W[$w]}" "${POL[$p]}" "$A1" "${SLO[$lv]}"
  fi
}
rm -f "$HERE"/configs/f615_*_o*_suite.tsv
Q="$HERE/configs/f615_queue.tsv"
echo "# F6.15 confirmation (polyaxon/f6_15_suites.sh): suffix<TAB>suite; ${#WORKLOADS[@]} workloads x $REPS reps" > "$Q"
n=${#UNITS[@]}
for rep in $(seq 1 "$REPS"); do
  for w in "${WORKLOADS[@]}"; do
    f="$HERE/configs/f615_${w}_o${rep}_suite.tsv"
    {
      echo "# F6.15 $w, rep $rep (polyaxon/f6_15_suites.sh; D52, D54): units rotated by $((4 * (rep - 1) % n))"
      for i in $(seq 0 $((n - 1))); do arm "$w" "${UNITS[$(((i + 4 * (rep - 1)) % n))]}"; done
    } > "$f"
    printf 'f615-%s-%s\tpolyaxon/configs/%s\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$(basename "$f")" >> "$Q"
  done
done
S="$HERE/configs/f615_smoke_suite.tsv"
{
  echo "# F6.15 smoke: A9.4 with lambda 1 at S6k2 and S3k5 on C1 n10 (lines from f615_C1n10_o1_suite.tsv)"
  grep -P "^(lvfp_S6k2_ps|lvfp_S3k5_ps)\t" "$HERE/configs/f615_C1n10_o1_suite.tsv"
} > "$S"
echo "wrote $(ls "$HERE"/configs/f615_*_o*_suite.tsv | wc -l) suites, queue $Q, smoke $S"
