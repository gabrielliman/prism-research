#!/bin/bash
# F6.0 suites (D31, D32, D49): deadline policies A2.1 (EDF between models, PRISM_EVICTION=edf), A9.1 (Virtual Lag
# Time, PRISM_EVICTION=lvf) and A9.2 (residency-aware lag, arm name lvfr: PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1,
# asked by Gabriel 2026-11-09) x SLO levels {S3 kA=5, S6 kR=1, 2, 4} x {without (p0), with (p1) preemption}, against the F5
# baselines, all with A1 (D38) and in the same job (rule 3). One job = one workload x one repetition.
#   A0.2_A1   idle threshold 10 s + A1 (best F5 baseline on SLO)
#   A0.4      throughput swap, no preemption, headroom 0 + A1 (best F5 baseline on tail / waits)
#   A0.4p     the same with preemption: not run by default (agent proposal 2026-11-09, pending Gabriel: its code changed with P16, F5 already
#             shows it is the worst, and the S3 question compares each deadline policy p0 vs p1); F60_BASE adds it
#   A0.1_A1   Prism as published + A1 (F5 paired reference); F60_BASE adds it
# The baselines that do run are the pairing references (rule 3, D49): F5's values are from another window.
# Deadline arms: the request's TTFT deadline is sent to the server (PRISM_OVL_SLO_SPEC; kD = 5 only enters the
# metrics); A1 on and activation headroom 0 as the A0.4 (D37 item 3: with A1 the kvcached floor replaces the
# headroom); T_min = A1.3 = 10 s; rotation budget 1 (code default); no drain (D30).
# Baselines do not depend on the SLO level (it is applied after the run), so they run once per job.
# Order: units = baselines and (policy, level) pairs; a pair's p0 and p1 run back to back (the S3 hypothesis compares
# them), which of the two goes first alternates with the repetition, and the unit order rotates by 4 per repetition.
# Writes polyaxon/configs/f60_<W>_o<rep>_suite.tsv and the driver queue polyaxon/configs/f60_queue.tsv (rep 1 of every
# workload, then rep 2, then rep 3; the driver packs jobs under its 36-worker budget: C1n10 10, T1 12, C6n14 14, T3 12).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPS=${F60_REPS:-2}  # D50: 2 reps (Gabriel 2026-11-09)
WORKLOADS=(${F60_WORKLOADS:-C1n10 T1 C6n14 T3})
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
declare -A W=(
  [C1n10]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2"
  [T1]="PRISM_STEPS=ovl_trace_big PRISM_OVL_RATES=1"
  [C6n14]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2 PRISM_OVL_N=14"
  [C8]="PRISM_STEPS=ovl_diurnal PRISM_OVL_RATES=2"
  [T3]="PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1"
)
declare -A ENV=(
  [A0.1_A1]="PRISM_IDLE_THRESHOLD=50 $A1"
  [A0.2_A1]="PRISM_IDLE_THRESHOLD=10 $A1"
  [A0.4]="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0 $A1"
  [A0.4p]="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=1 PRISM_ACTIVATION_HEADROOM_GB=0 $A1"
)
declare -A SLO=([S3k5]="S3:kA=5,kD=5" [S6k1]="S6:kR=1,kD=5" [S6k2]="S6:kR=2,kD=5" [S6k4]="S6:kR=4,kD=5")
UNITS=(${F60_BASE:-A0.2_A1 A0.4})
# D50 (Gabriel 2026-11-09): S6 kR=2 dropped (F5: the curves change smoothly between kR=1 and kR=4)
for pol in ${F60_POLICIES:-edf lvf lvfr}; do for lv in ${F60_LEVELS:-S3k5 S6k1 S6k4}; do UNITS+=("$pol:$lv"); done; done
arm() {  # name<TAB>vars of one arm
  local w=$1 name=$2
  if [[ $name == *_p[01] ]]; then
    local pol=${name%%_*} rest=${name#*_}; local lv=${rest%_p*} p=${name##*_p} ev
    ev=$([ "$pol" = lvfr ] && echo "lvf PRISM_LVF_COST_AWARE=1" || echo "$pol")
    printf '%s\t%s PRISM_EVICTION=%s PRISM_SWAP_PREEMPT=%s PRISM_ACTIVATION_HEADROOM_GB=0 %s PRISM_OVL_SLO_SPEC=%s\n' \
      "$name" "${W[$w]}" "$ev" "$p" "$A1" "${SLO[$lv]}"
  else
    printf '%s\t%s %s\n' "$name" "${W[$w]}" "${ENV[$name]}"
  fi
}
rm -f "$HERE"/configs/f60_*_suite.tsv
Q="$HERE/configs/f60_queue.tsv"
echo "# F6.0 (polyaxon/f6_0_suites.sh): suffix<TAB>suite; ${#WORKLOADS[@]} workloads x $REPS reps" > "$Q"
n=${#UNITS[@]}
for rep in $(seq 1 "$REPS"); do
  for w in "${WORKLOADS[@]}"; do
    f="$HERE/configs/f60_${w}_o${rep}_suite.tsv"
    {
      echo "# F6.0 $w, rep $rep (polyaxon/f6_0_suites.sh; D49): units rotated by $((4 * (rep - 1) % n))"
      for i in $(seq 0 $((n - 1))); do
        u=${UNITS[$(((i + 4 * (rep - 1)) % n))]}
        if [[ $u == *:* ]]; then
          first=$(( (rep + 1) % 2 )); second=$(( 1 - first ))
          arm "$w" "${u%%:*}_${u#*:}_p$first"; arm "$w" "${u%%:*}_${u#*:}_p$second"
        else
          arm "$w" "$u"
        fi
      done
    } > "$f"
    printf 'f60-%s-%s\tpolyaxon/configs/%s\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$(basename "$f")" >> "$Q"
  done
done
echo "wrote $(ls "$HERE"/configs/f60_*_suite.tsv | wc -l) suites, queue $Q"
