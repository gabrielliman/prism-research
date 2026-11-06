#!/bin/bash
# F4.4 campaign suites (2026-11-05, D34, Gabriel's scope: plan matrix 5 reps + D29 real-size loads 2 reps).
# One job = one workload x {A0.1, A0.3 without drain (D30)} x {without, with A1}: the 4 arms of a comparison run
# in the same job (same node window, rule 3). Two orders (a: as listed, b: reversed) alternate between reps so no
# arm always runs first or last in a job.
# A1 = A1.1 b=4 (+ kvcached 5% floor) + A1.2 Δ_imp=30 s + A1.3 T_min=10 s.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
A01="PRISM_IDLE_THRESHOLD=50"
A03="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=3"
declare -A W=(
  [C3]="PRISM_STEPS=ovl_mix PRISM_OVL_RATES=0.2"
  [C1n8]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_OVL_N=8"
  [C1n14]="PRISM_STEPS=ovl_mem PRISM_OVL_RATES=0.2 PRISM_OVL_N=14"
  [C2]="PRISM_STEPS=ovl_phases PRISM_OVL_RATES=0.5"
  [T1]="PRISM_STEPS=ovl_trace_big PRISM_OVL_RATES=1"
  [C6]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2"
  [C7]="PRISM_STEPS=ovl_bursty PRISM_OVL_RATES=0.2"
  [C8]="PRISM_STEPS=ovl_diurnal PRISM_OVL_RATES=2"
  [T3]="PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1"
  [C10]="PRISM_STEPS=ovl_sizes PRISM_OVL_RATES=0.2"
)
for w in "${!W[@]}"; do
  for o in a b; do
    f="$HERE/configs/f4_camp_${w}_${o}_suite.tsv"
    lines=("A0.1	${W[$w]} $A01" "A0.1_A1	${W[$w]} $A01 $A1" "A0.3	${W[$w]} $A03" "A0.3_A1	${W[$w]} $A03 $A1")
    {
      echo "# F4.4 $w, order $o (polyaxon/f4_suites.sh; D34): {A0.1, A0.3 no drain} x {without, with A1}, one rep per job"
      if [ "$o" = a ]; then printf '%s\n' "${lines[@]}"; else printf '%s\n' "${lines[3]}" "${lines[2]}" "${lines[1]}" "${lines[0]}"; fi
    } > "$f"
  done
done
ls "$HERE"/configs/f4_camp_*_suite.tsv | wc -l
