#!/bin/bash
# F4 headroom check (D37, Gabriel 2026-11-06): with A1 on, A0.3's 3 GB activation headroom stacks on A1.1's kvcached
# floor (F04 anomaly 4). One job = one workload x {A0.3; A0.3 + A1 with headroom 3 GB (the F4.4 arm); A0.3 + A1 with
# headroom 0 (candidate A0.4)}, same window; order alternates between the 2 reps.
# Workloads: where reading (b) of F4.5 failed (T3, C3, C7) and where A1 helped A0.3 (C6).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
A1="PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10"
TP="PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0"
declare -A W=(
  [T3]="PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1"
  [C3]="PRISM_STEPS=ovl_mix PRISM_OVL_RATES=0.2"
  [C7]="PRISM_STEPS=ovl_bursty PRISM_OVL_RATES=0.2"
  [C6]="PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2"
)
Q="$HERE/configs/f4_folga_queue.tsv"
echo "# F4 headroom check (D37): suffix<TAB>suite" > "$Q"
for rep in 1 2; do
  for w in T3 C3 C7 C6; do
    o=$([ $rep = 1 ] && echo a || echo b)
    f="$HERE/configs/f4_folga_${w}_${o}_suite.tsv"
    l1="A0.3	${W[$w]} $TP PRISM_ACTIVATION_HEADROOM_GB=3"
    l2="A0.3_A1	${W[$w]} $TP PRISM_ACTIVATION_HEADROOM_GB=3 $A1"
    l3="A0.3_A1h0	${W[$w]} $TP PRISM_ACTIVATION_HEADROOM_GB=0 $A1"
    {
      echo "# F4 headroom check $w, order $o (polyaxon/f4_folga_suites.sh; D37)"
      if [ "$o" = a ]; then printf '%s\n' "$l1" "$l2" "$l3"; else printf '%s\n' "$l3" "$l2" "$l1"; fi
    } > "$f"
    printf 'f4-folga-%s-%s\tpolyaxon/configs/%s\n' "$(echo "$w" | tr A-Z a-z)" "$rep" "$(basename "$f")" >> "$Q"
  done
done
cat "$Q"
