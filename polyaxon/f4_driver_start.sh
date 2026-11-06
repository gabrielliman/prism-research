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
fi
setsid nohup /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_driver.py >> "$log" 2>&1 < /dev/null &
echo "driver pid $! (log $log)"
