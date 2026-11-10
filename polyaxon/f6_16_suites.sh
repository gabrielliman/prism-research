#!/bin/bash
# F6.16 screening suites (D52, D53): the new policies against the F5 baselines and the A9.2 reference, 2 repetitions,
# all with A1 (D38) and in the same job (rule 3). One job = one workload x one repetition. No global preemption (D52).
#   A0.2_A1          idle threshold 10 s + A1
#   A0.4             throughput swap, no preemption, headroom 0 + A1
#   lvfr_<lv>_p0     A9.2 residency-aware VLT, no preemption (reference, D53)
#   lvfp_<lv>_ps     A9.4 = A9.2 deciding preemption per swap (Shepherd rule, lambda 3)
#   loss_<lv>_p0     A3.1 expected deadline loss
#   value_<lv>_p0    A10.1 throughput swap restricted to waiting models with a viable request
#   pred_<lv>_p0     A2.3 = A9.2 + predictive residency (expected arrival while away)
# Levels (<lv>): S3k5 (S3 kA=5, ~7 s for an 8B) and S6k1 (S6 kR=1, ~16 s): the deadline is sent per request
# (PRISM_OVL_SLO_SPEC; kD = 5 only in the metrics). The baselines do not depend on it and run once per job.
# Order: units = baselines and policies (each policy's two levels back to back); the unit order rotates by 3 per
# repetition. Writes polyaxon/configs/f616_<W>_o<rep>_suite.tsv and the driver queue polyaxon/configs/f616_queue.tsv.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPS=${F616_REPS:-2}
WORKLOADS=(${F616_WORKLOADS:-C1n10 T1 C6n14 T3})
LEVELS=(${F616_LEVELS:-S3k5 S6k1})
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
  [lvfr]="PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1"
  [lvfp]="PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_LVF_PREEMPT=per_swap PRISM_LVF_PREEMPT_LAMBDA=3"
  [loss]="PRISM_EVICTION=loss"
  [value]="PRISM_EVICTION=value"
  [pred]="PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_LVF_PREDICTIVE=1"
)
declare -A TAG=([lvfr]=p0 [lvfp]=ps [loss]=p0 [value]=p0 [pred]=p0)
declare -A SLO=([S3k5]="S3:kA=5,kD=5" [S6k1]="S6:kR=1,kD=5")
UNITS=(A0.2_A1 A0.4 lvfr lvfp loss value pred)
rm -f "$HERE"/configs/f616_*_o*_suite.tsv
Q="$HERE/configs/f616_queue.tsv"
echo "# F6.16 screening (polyaxon/f6_16_suites.sh): suffix<TAB>suite; ${#WORKLOADS[@]} workloads x $REPS reps" > "$Q"
n=${#UNITS[@]}
for rep in $(seq 1 "$REPS"); do
  for w in "${WORKLOADS[@]}"; do
    f="$HERE/configs/f616_${w}_o${rep}_suite.tsv"
    {
      echo "# F6.16 $w, rep $rep (polyaxon/f6_16_suites.sh; D52, D53): units rotated by $((3 * (rep - 1) % n))"
      for i in $(seq 0 $((n - 1))); do
        u=${UNITS[$(((i + 3 * (rep - 1)) % n))]}
        if [ -n "${BASE[$u]:-}" ]; then
          printf '%s\t%s %s\n' "$u" "${W[$w]}" "${BASE[$u]}"
        else
          for lv in "${LEVELS[@]}"; do
            printf '%s_%s_%s\t%s %s PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0 %s PRISM_OVL_SLO_SPEC=%s\n' \
              "$u" "$lv" "${TAG[$u]}" "${W[$w]}" "${POL[$u]}" "$A1" "${SLO[$lv]}"
          done
        fi
      done
    } > "$f"
    printf 'f616-%s-%s\tpolyaxon/configs/%s\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$(basename "$f")" >> "$Q"
  done
done
# smoke: every new policy once on C1 (10 models)
S="$HERE/configs/f616_smoke_suite.tsv"
{
  echo "# F6.16 smoke: A9.4, A3.1, A10.1, A2.3 once each on C1 n10 (lines from f616_C1n10_o1_suite.tsv)"
  grep -P "^(lvfp_S3k5_ps|loss_S6k1_p0|value_S6k1_p0|pred_S3k5_p0)\t" "$HERE/configs/f616_C1n10_o1_suite.tsv"
} > "$S"
echo "wrote $(ls "$HERE"/configs/f616_*_o*_suite.tsv | wc -l) suites, queue $Q, smoke $S"
