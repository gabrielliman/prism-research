#!/bin/bash
# F5.1 campaign suites (D39 scope, D40: 3 jobs at a time, 3 repetitions).
# One job = one workload x the 5 configurations (rule 3: the arms of a comparison run in the same job, same node
# window). The order of the arms rotates between repetitions (rep r starts at arm 2(r-1) mod 5), so no arm always runs
# first or last. A1 = A1.1 b=4 (+ kvcached 5% floor) + A1.2 30 s + A1.3 10 s (D38).
#   A0.1      Prism as published, idle threshold 50 s, WITHOUT A1 (reference for the freeze)
#   A0.1_A1   the same + A1
#   A0.2_A1   idle threshold 10 s + A1
#   A0.4      throughput swap, no preemption, no fixed headroom + A1 (D37, D38)
#   A0.4p     the same with preemption (D39)
# Workloads: rho_mem sweep 1.07 / 1.5 / 2.0 = 10 / 14 / 19 x 8B (PRISM_OVL_N) on C1 (rate per model fixed at 0.2, so
# the total rate grows with N) and C6 (total rate fixed at 2 req/s, spread by Zipf over N); every other approved
# workload (D29) at its approved level. Writes polyaxon/configs/f5_camp_<W>_o<k>_suite.tsv, the queue
# polyaxon/configs/f5_camp_queue.tsv (rep 1 of every workload, then rep 2, then rep 3) and the smoke suite/queue.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPS=${F5_REPS:-3}
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
A04="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0"
A04P="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=1 PRISM_ACTIVATION_HEADROOM_GB=0"
ARMS=("A0.1" "A0.1_A1" "A0.2_A1" "A0.4" "A0.4p")
declare -A ENV=(
  [A0.1]="PRISM_IDLE_THRESHOLD=50"
  [A0.1_A1]="PRISM_IDLE_THRESHOLD=50 $A1"
  [A0.2_A1]="PRISM_IDLE_THRESHOLD=10 $A1"
  [A0.4]="$A04 $A1"
  [A0.4p]="$A04P $A1"
)
# Queue order (D47): each 19-model job is followed by the smallest ones (C5 2 workers, C4 4, C10 8), so the node-wide
# worker budget of the driver (F4_MAX_WORKERS=36) leaves fewer slots idle. Rep 1 of C1n10/C1n14/C1n19/C6n10/C6n14 was
# submitted before D47 in the original order (C1n10 C1n14 C1n19 C6n10 C6n14 ...).
ORDER=(C1n10 C1n14 C6n10 C6n14 C1n19 C5 C4 C6n19 C10 C2 C3 T1 C7 C8 C9C1 C9C6 T3 T2)
# Re-runs (whole job again, so the 5 arms share one window, rule 3): <workload>:<rep>:<tag>, suffix -<rep><tag>,
# queued first. b = D47 (K1 with 43 workers on the node); C5:1:b = health check failed next to the C1 14/19 jobs (D48);
# T3:1:b = K1 at start-up, job stopped by the D48 abort (2026-11-08 00:34 UTC).
RERUN=(C1n14:1:b C1n19:1:b C1n10:1:b C5:1:b T3:1:b)
# D48: C1 with 14 and 19 models runs alone on the node (driver F4_EXCLUSIVE='_C1n1[49]_'); they go together at the
# end of the queue (one drain of the node), after every other job: the -1c re-runs, then reps 2 and 3.
EXCL=(C1n14 C1n19)
EXCL_RERUN=(C1n14:1:c C1n19:1:c)
declare -A W=(
  [C1n10]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2"
  [C1n14]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_OVL_N=14"
  [C1n19]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_OVL_N=19"
  [C6n10]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2"
  [C6n14]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2 PRISM_OVL_N=14"
  [C6n19]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2 PRISM_OVL_N=19"
  [C2]="PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5"
  [C3]="PRISM_STEPS=ovl_mix PRISM_OVL_RATES=0.2"
  [T1]="PRISM_STEPS=ovl_trace_big PRISM_OVL_RATES=1"
  [C7]="PRISM_STEPS=ovl_bursty PRISM_OVL_RATES=0.2"
  [C8]="PRISM_STEPS=ovl_diurnal PRISM_OVL_RATES=2"
  [C9C1]="PRISM_STEPS=ovl_classes PRISM_OVL_RATES=0.2"
  [C9C6]="PRISM_STEPS=ovl_classes PRISM_OVL_CLASS_BASE=zipf PRISM_OVL_RATES=2"
  [T3]="PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1"
  [T2]="PRISM_STEPS=ovl_tr_lmsys PRISM_OVL_RATES=1"
  [C10]="PRISM_STEPS=ovl_sizes PRISM_OVL_RATES=0.2"
  [C4]="PRISM_STEPS=ovl_kv PRISM_OVL_RATES=0.5"
  [C5]="PRISM_STEPS=ovl_compute PRISM_OVL_RATES=25"
)
rm -f "$HERE"/configs/f5_camp_*_suite.tsv
Q="$HERE/configs/f5_camp_queue.tsv"
echo "# F5.1 campaign (polyaxon/f5_suites.sh): suffix<TAB>suite; ${#ORDER[@]} workloads x $REPS reps" > "$Q"
rerun() { local w rep tag; IFS=: read -r w rep tag <<< "$1"
  printf 'f5-%s-%s%s\tpolyaxon/configs/f5_camp_%s_o%s_suite.tsv\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$tag" "$w" "$rep" >> "$Q"; }
for x in "${RERUN[@]}"; do rerun "$x"; done
for rep in $(seq 1 "$REPS"); do
  for w in "${ORDER[@]}"; do
    f="$HERE/configs/f5_camp_${w}_o${rep}_suite.tsv"
    {
      echo "# F5.1 $w, rep $rep (polyaxon/f5_suites.sh; D39): 5 configurations, order rotated by $((2 * (rep - 1) % 5))"
      for i in 0 1 2 3 4; do
        a=${ARMS[$(((i + 2 * (rep - 1)) % 5))]}
        printf '%s\t%s %s\n' "$a" "${W[$w]}" "${ENV[$a]}"
      done
    } > "$f"
    [[ " ${EXCL[*]} " == *" $w "* ]] && [ "$rep" -gt 1 ] && continue  # D48: at the end (rep 1 ran before D48)
    printf 'f5-%s-%s\tpolyaxon/configs/%s\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$(basename "$f")" >> "$Q"
  done
done
for x in "${EXCL_RERUN[@]}"; do rerun "$x"; done
for rep in $(seq 2 "$REPS"); do
  for w in "${EXCL[@]}"; do
    printf 'f5-%s-%s\tpolyaxon/configs/f5_camp_%s_o%s_suite.tsv\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$w" "$rep" >> "$Q"
  done
done
# Smoke (before the campaign): start-up and a short level with 14 and 19 workers on one GPU (a 14-worker start-up
# failure was once logged with ovl_mix, run_examples.sh), under the configurations with most transitions.
S="$HERE/configs/f5_smoke_suite.tsv"
SHORT="PRISM_OVL_DURATION=120 PRISM_OVL_DRAIN=120"
{
  echo "# F5 smoke (polyaxon/f5_suites.sh): rho_mem 1.5 / 2.0 start-up and short levels"
  printf 'C1n19_A0.4p\t%s %s %s\n' "${W[C1n19]}" "$SHORT" "${ENV[A0.4p]}"
  printf 'C6n19_A0.1_A1\t%s %s %s\n' "${W[C6n19]}" "$SHORT" "${ENV[A0.1_A1]}"
  printf 'C6n14_A0.4\t%s %s %s\n' "${W[C6n14]}" "$SHORT" "${ENV[A0.4]}"
} > "$S"
printf '# F5 smoke: 1 = code f6f7678 (pre-D45), 2 = after D45 (f279ced)\nf5-smoke-1\tpolyaxon/configs/%s\nf5-smoke-2\tpolyaxon/configs/%s\n' "$(basename "$S")" "$(basename "$S")" > "$HERE/configs/f5_smoke_queue.tsv"
echo "$(ls "$HERE"/configs/f5_camp_*_suite.tsv | wc -l) suites, $(grep -vc '^#' "$Q") jobs, $(( $(grep -vc '^#' "$Q") * 5 )) levels"
