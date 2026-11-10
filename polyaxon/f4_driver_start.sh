#!/bin/bash
# Start an F4 campaign driver detached from the terminal (resumable).
#   default: the F4.4 campaign, state reports/data/F04/campanha_jobs.tsv, log reports/data/F04/driver.log
#   bash polyaxon/f4_driver_start.sh folga   -> headroom check (D37): queue polyaxon/configs/f4_folga_queue.tsv,
#                                                state reports/data/F04/folga_jobs.tsv, log reports/data/F04/driver_folga.log
cd "$(dirname "$0")/.."
log=reports/data/F04/driver.log
if [ "${1:-}" = folga ]; then
  export F4_QUEUE=polyaxon/configs/f4_folga_queue.tsv F4_STATE=reports/data/F04/folga_jobs.tsv
  log=reports/data/F04/driver_folga.log
elif [ "${1:-}" = f5ded ]; then  # F5 dedicated base (polyaxon/f5_ded_suites.sh)
  mkdir -p reports/data/F05/validador
  export F4_QUEUE=polyaxon/configs/f5_ded_queue.tsv F4_STATE=reports/data/F05/ded_jobs.tsv \
    F4_RAW=/mnt/scratch/scheduler/prism-raw/F5/ded F4_VAL=reports/data/F05/validador F4_TIMEOUT=14400
  log=reports/data/F05/driver_ded.log
elif [ "${1:-}" = f5smoke ] || [ "${1:-}" = f5 ]; then  # F5.1 smoke / campaign (polyaxon/f5_suites.sh)
  k=$([ "$1" = f5 ] && echo camp || echo smoke)
  mkdir -p reports/data/F05/$k/validador
  export F4_QUEUE=polyaxon/configs/f5_${k}_queue.tsv F4_STATE=reports/data/F05/$k/jobs.tsv \
    F4_RAW=/mnt/scratch/scheduler/prism-raw/F5/$k F4_VAL=reports/data/F05/$k/validador F4_TIMEOUT=14400 \
    F4_MAX_WORKERS=36 F4_EXCLUSIVE='_C1n1[49]_'  # D47 worker budget; D48 C1 14/19 models alone on the node
  log=reports/data/F05/$k/driver.log
elif [ "${1:-}" = f60 ]; then  # F6.0 (polyaxon/f6_0_suites.sh): 20 levels per job, up to ~6.5 h
  mkdir -p reports/data/F06/f60/validador
  export F4_QUEUE=polyaxon/configs/f60_queue.tsv F4_STATE=reports/data/F06/f60/jobs.tsv \
    F4_RAW=/mnt/scratch/scheduler/prism-raw/F6/f60 F4_VAL=reports/data/F06/f60/validador F4_TIMEOUT=36000 \
    F4_MAX_WORKERS=0  # D50: no worker budget (D48: K1 is not the worker count); 3 jobs max still (F4_MAX_ACTIVE)
  log=reports/data/F06/f60/driver.log
elif [ "${1:-}" = f616 ]; then  # F6.16 screening (polyaxon/f6_16_suites.sh): 12 levels per job, up to ~4 h
  mkdir -p reports/data/F06/f616/validador
  export F4_QUEUE=polyaxon/configs/f616_queue.tsv F4_STATE=reports/data/F06/f616/jobs.tsv \
    F4_RAW=/mnt/scratch/scheduler/prism-raw/F6/f616 F4_VAL=reports/data/F06/f616/validador F4_TIMEOUT=25200 \
    F4_MAX_WORKERS=0  # D50: no worker budget; 3 jobs max (F4_MAX_ACTIVE)
  log=reports/data/F06/f616/driver.log
fi
setsid nohup /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_driver.py >> "$log" 2>&1 < /dev/null &
echo "driver pid $! (log $log)"
