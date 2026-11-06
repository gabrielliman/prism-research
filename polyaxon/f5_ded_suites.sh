#!/bin/bash
# F5 prerequisite (F03 pending item, D20/D21): dedicated-GPU base of the S2/S2M SLO families for the F3 workloads.
# Each model's own requests of the workload's approved level, alone on a GPU (PRISM_OVL_DEDICATED, F2.10), so
# polyaxon/iso_dedicated.py can build the pooled P95/P50 TTFT/TPOT base into reports/registro/latencia_ded.json.
# C9 (ovl_classes) reuses the C1 and C6 bases. A1 is irrelevant here (one model, never evicted).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IDLE="PRISM_IDLE_THRESHOLD=100000"
Q="$HERE/configs/f5_ded_queue.tsv"
echo "# F5 dedicated base (S2/S2M): suffix<TAB>suite" > "$Q"
mk() {  # name, step vars, dedicated target list
  f="$HERE/configs/f5_ded_$1_suite.tsv"
  { echo "# F5 dedicated base $1 (polyaxon/f5_ded_suites.sh)"; printf '%s\t%s PRISM_OVL_DEDICATED=%s %s\n' "$1" "$2" "$3" "$IDLE"; } > "$f"
  printf 'f5-ded-%s\tpolyaxon/configs/%s\n' "$(echo "$1" | tr A-Z a-z)" "$(basename "$f")" >> "$Q"
}
mk C8a "PRISM_STEPS=ovl_diurnal PRISM_OVL_RATES=2" "'model_1 model_2 model_3 model_4 model_5'"
mk C8b "PRISM_STEPS=ovl_diurnal PRISM_OVL_RATES=2" "'model_6 model_7 model_8 model_9 model_10'"
mk C10 "PRISM_STEPS=ovl_sizes PRISM_OVL_RATES=0.2" all
mk C6 "PRISM_STEPS=ovl_zipf PRISM_OVL_RATES=2" all
mk C7 "PRISM_STEPS=ovl_bursty PRISM_OVL_RATES=0.2" all
mk T3 "PRISM_STEPS=ovl_tr_azfn PRISM_OVL_RATES=1" all
mk T2 "PRISM_STEPS=ovl_tr_lmsys PRISM_OVL_RATES=1" all
cat "$Q"
