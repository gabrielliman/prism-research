#!/bin/bash
# F5.0a census of real rotation costs (D32): validator on the 28/10 throughput-swap jobs (they predate the validator),
# then polyaxon/swap_cost.py on every VALIDA level of F4 (swap without drain, D30), F6a (with drain) and 28/10
# (P0/P1 x D0/D1). Output: reports/data/F05/swap_cost/{rotacoes.csv,resumo.md,c_rot.json}.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=reports/data/F05/swap_cost
mkdir -p "$OUT/validador_2810"
for j in /mnt/scratch/scheduler/prism-raw/2026-10-28/*/*tp-*; do
  n="$(basename "$(dirname "$j")")_$(basename "$j")"
  find "$j" -name summary.json -print -quit | grep -q . || continue  # some 28/10 job folders are empty
  [ -f "$OUT/validador_2810/$n.csv" ] || python3 polyaxon/validate_run.py --csv "$OUT/validador_2810/$n.csv" "$j" | tail -1
done
F4=$(ls reports/data/F04/validador/f4-*.csv | grep -v "f4-c10-1.csv\|f4-c10-2.csv")
/mnt/scratch/scheduler/opt-env/bin/python polyaxon/swap_cost.py "$OUT" $F4 reports/data/F06a/validador/*.csv \
  "$OUT"/validador_2810/*.csv
