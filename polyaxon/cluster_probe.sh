#!/bin/bash
# Node/GPU performance probe (2026-10-30): snapshot of the node state plus fixed microbenchmarks
# (polyaxon/cluster_probe.py), with GPU clocks/power/throttle reasons and host CPU/memory pressure sampled
# while they run. Submit with: polyaxon/submit.sh cluster_probe   (PRISM_JOB_SUFFIX names the run)
# Results in $PRISM_RESULTS: node.txt, nvidia_smi_q.txt, gpu_samples.csv, host_samples.log, probe.json, probe.log,
# probe_pin_local.json / probe_pin_remote.json (CPU-sensitive benchmarks pinned to the GPU's NUMA node / the other one);
# node.txt also gets vmm_parallel_1/10 (kvcached start-up of 1 / 10 processes: how many succeeded, seconds).
set -u
OUT="${PRISM_RESULTS:-/tmp/probe}"
mkdir -p "$OUT"
{
  echo "start_utc: $(date -u +%FT%TZ)"
  echo "hostname: $(hostname)"
  for v in NODE_NAME KUBERNETES_NODE_NAME POLYAXON_RUN_UUID; do echo "$v: ${!v:-}"; done
  echo "nproc: $(nproc)  affinity: $(python3 -c 'import os; print(len(os.sched_getaffinity(0)))')"
  lscpu | grep -E "^(Model name|Socket|Core|Thread|CPU\(s\)|NUMA node\(s\)|CPU max MHz)"
  echo "loadavg: $(cat /proc/loadavg)"
  for f in /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; do echo "$f:"; cat "$f" 2>/dev/null; done
  for f in /sys/fs/cgroup/cpu.max /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.max; do echo "$f:"; cat "$f" 2>/dev/null; done
  free -g
  nvidia-smi --query-gpu=index,uuid,serial,pci.bus_id,name,driver_version,power.limit,power.max_limit,clocks.max.sm,clocks.max.mem,pcie.link.gen.max,pcie.link.width.max --format=csv
  nvidia-smi topo -m
} > "$OUT/node.txt" 2>&1
nvidia-smi -q > "$OUT/nvidia_smi_q.txt" 2>&1
cat "$OUT/node.txt"

nvidia-smi --query-gpu=timestamp,utilization.gpu,clocks.sm,clocks.mem,power.draw,temperature.gpu,clocks_throttle_reasons.active,pcie.link.gen.current,pcie.link.width.current,memory.used \
  --format=csv,nounits -lms 500 > "$OUT/gpu_samples.csv" 2>/dev/null &
SMI=$!
( while true; do
    echo "$(date -u +%T) load=$(cut -d' ' -f1-4 /proc/loadavg) cpu_psi=$(head -1 /proc/pressure/cpu 2>/dev/null) mem_psi=$(head -1 /proc/pressure/memory 2>/dev/null)"
    sleep 5
  done ) > "$OUT/host_samples.log" 2>&1 &
HOST=$!
python3 polyaxon/cluster_probe.py "$OUT" --reps "${PROBE_REPS:-3}" 2>&1 | tee "$OUT/probe.log"
# CUDA VMM test: the kvcached start-up of Prism's workers (polyaxon/kvcached_probe.py --parallel, the same check as
# run_examples.sh health_gate): 1 process, then 10 at once, each mapping 25 GB of virtual KV space in 2 MB pages
for n in 1 10; do
  echo "vmm_parallel_$n: $(python3 polyaxon/kvcached_probe.py --parallel $n 2>&1 | grep -E '^health:' | tail -1)" | tee -a "$OUT/node.txt"
done
# NUMA test: the CPU-sensitive benchmarks pinned to the GPU's local NUMA node and to the remote one
LOCAL=$(nvidia-smi topo -m 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk '$1=="GPU0"{for(i=2;i<=NF;i++) if ($i ~ /^[0-9]+-[0-9]+$/) {print $i; exit}}')
if [ -n "$LOCAL" ]; then
  lo=${LOCAL%-*}; hi=${LOCAL#*-}; n=$(nproc)
  if [ "$lo" = 0 ]; then REMOTE="$((hi + 1))-$((n - 1))"; else REMOTE="0-$((lo - 1))"; fi
  echo "numa: local cpus $LOCAL, remote cpus $REMOTE" | tee -a "$OUT/node.txt"
  taskset -c "$LOCAL" python3 polyaxon/cluster_probe.py "$OUT" --pin-label local 2>&1 | tee -a "$OUT/probe.log"
  taskset -c "$REMOTE" python3 polyaxon/cluster_probe.py "$OUT" --pin-label remote 2>&1 | tee -a "$OUT/probe.log"
fi
kill $SMI $HOST 2>/dev/null
nvidia-smi -q -d PERFORMANCE,CLOCK,POWER,TEMPERATURE > "$OUT/nvidia_smi_q_end.txt" 2>&1
echo "end_utc: $(date -u +%FT%TZ)" >> "$OUT/node.txt"
