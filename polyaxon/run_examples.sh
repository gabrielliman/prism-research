#!/bin/bash
# Runs the README examples on Polyaxon (see prism_examples.yaml / submit.sh).
# Steps (PRISM_STEPS, default "static elastic prism1"; prism2 needs a 2-GPU job):
#   static  - README example 1: 2 models colocated, static memory, --load-format dummy
#   elastic - README example 2: 2 models colocated, elastic memory (kvcached)
#   prism1  - README example 3 (full Prism flags) on 1 GPU: 1_gpu_2_model_our.json
#   prism2  - README example 3 on 2 GPUs: 8_gpu_18_model_our.json limited to GPUs 0-1 (6 models)
#   overload - example 3 on 1 GPU, 8 models over the memory budget, trace at PRISM_TIME_SCALES
#   ovl_mem / ovl_phases / ovl_kv / ovl_compute / ovl_trace / ovl_mix - real overload scenarios (see the step below)
# PRISM_IDLE_THRESHOLD=<s>: the global controller's idle-eviction threshold (default 50 s); the
# controller cycle (PRISM_SCHEDULE_INTERVAL, default 5 s) then defaults to min(5, threshold).
# The README e2e benchmark (no --model-paths) always targets all 18 models, so prism1/2 pass
# --model-paths model_1..N (benchmark.py's subset path) to only send to the models served.
# Redis (install.md step 1) is started once for all steps.
# Gated base models are not in the cluster HF cache, so the configs are copied with the
# same-architecture Instruct variants that are cached there. Everything else is as in the README.
set -u
# Image: gabrielliman/prism (lmsysorg/sglang:v0.3.4.post2-cu121 + install.md steps, docker/prism).
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
RESULTS="${PRISM_RESULTS:-$ROOT/results}"; mkdir -p "$RESULTS"
exec > >(tee -a "$RESULTS/run.log") 2>&1

# PRISM_SUITE=<file>: run several configurations one after another in this job, so they never share
# the node with each other. Each line: <name><TAB><VAR=value ...>; results go to $RESULTS/<name>/.
if [ -n "${PRISM_SUITE:-}" ]; then
  echo "suite $PRISM_SUITE start $(date -u +%FT%TZ)"
  while IFS=$'\t' read -r name vars; do
    [ -z "$name" ] || [[ $name = \#* ]] && continue
    echo; echo "======== suite: $name ($vars) $(date -u +%T) ========"
    eval "env PRISM_SUITE= PRISM_RESULTS='$RESULTS/$name' $vars bash '$ROOT/polyaxon/run_examples.sh'" < /dev/null
    echo "======== suite: $name exit=$? $(date -u +%T) ========"
  done < "$PRISM_SUITE"
  echo "suite end $(date -u +%FT%TZ)"
  exit 0
fi

STEPS="${PRISM_STEPS:-static elastic prism1}"; STEPS="${STEPS//,/ }"  # commas or spaces
if [ -n "${PRISM_IDLE_THRESHOLD:-}" ]; then
  export PRISM_IDLE_THRESHOLD
  export PRISM_SCHEDULE_INTERVAL="${PRISM_SCHEDULE_INTERVAL:-$(python3 -c "print(min(5.0, $PRISM_IDLE_THRESHOLD))")}"
fi
STARTUP_TIMEOUT="${PRISM_STARTUP_TIMEOUT:-1200}"
echo "start $(date -u +%FT%TZ) steps: $STEPS  backend: ${PRISM_BACKEND:-sglang}  results: $RESULTS"
echo "idle threshold: ${PRISM_IDLE_THRESHOLD:-50 (default)} s, controller cycle: ${PRISM_SCHEDULE_INTERVAL:-5 (default)} s"

pip install -q -e python --no-deps

# The shared cache has no transformers `version.txt`, so transformers 4.46 runs its cache "migration"
# on import. Its tqdm bar creates a multiprocessing lock, which fixes the start method before
# launch_multi_model_server calls set_start_method("spawn") -> "context has already been set".
# Use a private HF_HOME of symlinks to the shared models (read-only use) plus that marker file.
SHARED_HUB="${HF_HOME:-/scratch/hpc4ai/hf_cache}/hub"
export HF_HOME=/tmp/hf_home
mkdir -p "$HF_HOME/hub" && echo 1 > "$HF_HOME/hub/version.txt"
for d in "$SHARED_HUB"/models--*; do ln -sfn "$d" "$HF_HOME/hub/$(basename "$d")"; done
echo "HF_HOME=$HF_HOME -> $(ls "$HF_HOME/hub" | grep -c models--) models linked from $SHARED_HUB"
{ nvidia-smi; pip freeze | grep -iE "^(sglang|vllm|torch|flashinfer|kvcached|transformers)"; } > "$RESULTS/environment.txt" 2>&1
cat "$RESULTS/environment.txt"

SERVER_PID=""; REDIS_PID=""
# Each server runs in its own process group (setsid), so stopping it also stops the spawned
# engine/scheduler children: they run as `python3 -c "from multiprocessing.spawn ..."`, hold the
# NCCL ports (server port + 1, + 2, ...: the next example's README port) and GPU memory.
stop_server() {
  [ -z "$SERVER_PID" ] && return 0
  kill -TERM -- "-$SERVER_PID" 2>/dev/null
  for _ in $(seq 1 30); do kill -0 -- "-$SERVER_PID" 2>/dev/null || break; sleep 1; done
  kill -KILL -- "-$SERVER_PID" 2>/dev/null
  SERVER_PID=""
  sleep 3
}
# wait_ports_free <port> <n>: wait until port..port+n are bindable (what the server checks).
wait_ports_free() {
  python3 - "$1" "$2" <<'PY2'
import socket, sys, time
p0, n = int(sys.argv[1]), int(sys.argv[2])
def free(p):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: s.bind(("", p)); return True
        except OSError: return False
for _ in range(60):
    busy = [p for p in range(p0, p0 + n + 1) if not free(p)]
    if not busy: sys.exit(0)
    time.sleep(1)
print("ports still busy:", busy); sys.exit(1)
PY2
}
cleanup() { stop_server; [ -n "$REDIS_PID" ] && kill "$REDIS_PID" 2>/dev/null; }
trap cleanup EXIT INT TERM

# install.md step 1: every mode talks to redis on localhost:6379 (install.md runs it via docker).
redis-server --port 6379 --save "" --daemonize no > "$RESULTS/redis.log" 2>&1 &
REDIS_PID=$!
for _ in $(seq 1 20); do redis-cli -p 6379 ping 2>/dev/null | grep -q PONG && break; sleep 0.5; done
echo "redis: $(redis-cli -p 6379 ping 2>&1)"

# profile_missing <config>: the GPU scheduler needs every model_path in
# python/sglang/multi_model/utils/model_info.json (weights size + KV cell size). Missing ones are
# estimated from the checkpoint (estimate_model_info.py: no GPU, within ~1% of the profiled values)
# and added to this job's uploaded copy only. profile_model_info.py is not used: its __main__ has a
# fixed model list and rewrites the file, and its vLLM 0.6.3 loader fails on Qwen2 checkpoints.
profile_missing() {
  local cfg=$1; [[ $cfg = /* ]] || cfg="$ROOT/$cfg"
  python3 -m sglang.multi_model.utils.estimate_model_info --write \
    $(python3 -c "import json;print(' '.join(sorted({m['model_path'] for m in json.load(open('$cfg'))})))")
}

# Copy a README config, swapping gated base models for the cached Instruct variants.
make_config() {
  python3 - "$1" "$2" <<'PY'
import json, sys
swap = {"meta-llama/Llama-3.1-8B": "meta-llama/Llama-3.1-8B-Instruct",
        "meta-llama/Llama-3.2-3B": "meta-llama/Llama-3.2-3B-Instruct",
        "meta-llama/Llama-3.2-1B": "meta-llama/Llama-3.2-3B-Instruct"}
cfg = json.load(open(sys.argv[1]))
for m in cfg:
    for k in ("model_path", "tokenizer_path"):
        if k in m:
            m[k] = swap.get(m[k], m[k])
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
print("config", sys.argv[2], [m["model_path"] for m in cfg])
PY
}

# start_server <step> <port> <config> <extra flags...>; waits until every "on" model is ready.
# PRISM_BACKEND=vllm (image gabrielliman/prism:vllm0.30-kvcached0.1.6): run every example with
# --engine-backend vllm (--use-kvcached-v0 is dropped: that backend uses upstream kvcached).
# PRISM_NO_WORKER_POOL=1 drops the worker-pool flags (worker pool, model service, CPU shared-memory
# weights) for either backend, to compare with and without the worker pool.
backend_args() {
  [ "${PRISM_BACKEND:-sglang}" = vllm ] && { echo --engine-backend; echo vllm; }
  while [ $# -gt 0 ]; do
    case $1 in
      --enable-cpu-share-memory|--enable-model-service|--enable-worker-pool)
        [ "${PRISM_NO_WORKER_POOL:-0}" = 1 ] || echo "$1" ;;
      --workers-per-gpu|--num-model-service-workers)
        [ "${PRISM_NO_WORKER_POOL:-0}" = 1 ] || { echo "$1"; echo "$2"; }; shift ;;
      --use-kvcached-v0) [ "${PRISM_BACKEND:-sglang}" = vllm ] || echo "$1" ;;
      *) printf '%s\n' "$1" ;;
    esac
    shift
  done
}

start_server() {
  local step=$1 port=$2 cfg=$3; shift 3
  mapfile -t args < <(backend_args "$@"); set -- "${args[@]}"
  local n_on; n_on=$(python3 -c "import json;print(sum(any(p['on'] for p in m['init_placements']) for m in json.load(open('$cfg'))))")
  mkdir -p "$RESULTS/$step"
  wait_ports_free "$port" 8 || return 1
  setsid python3 -m sglang.launch_multi_model_server --model-config-file "$cfg" \
    --host 127.0.0.1 --port "$port" "$@" --log-file "$RESULTS/$step/server_file.log" \
    > "$RESULTS/$step/server.log" 2>&1 &
  SERVER_PID=$!
  for i in $(seq 1 $((STARTUP_TIMEOUT / 5))); do
    kill -0 $SERVER_PID 2>/dev/null || { echo "[$step] SERVER DIED"; tail -60 "$RESULTS/$step/server.log"; stop_server; return 1; }
    ready=$(cat "$RESULTS/$step"/server*.log 2>/dev/null | grep -c "is fired up and ready to roll")
    if [ "$ready" -ge "$n_on" ] && curl -sf -o /dev/null "http://127.0.0.1:$port/health"; then
      echo "[$step] server ready in ~$((i * 5))s ($ready/$n_on models)"; return 0
    fi
    sleep 5
  done
  echo "[$step] SERVER NOT READY after ${STARTUP_TIMEOUT}s"; tail -60 "$RESULTS/$step/server.log"; stop_server; return 1
}

run_bench() {
  local step=$1; shift
  mkdir -p "$RESULTS/$step"
  echo "[$step] benchmark: $*"
  (cd benchmark/multi-model && timeout -k 30 "${BENCH_TIMEOUT:-0}" python3 benchmark.py "$@" \
      --results-path "$RESULTS/$step/benchmark-results" --request-path "$RESULTS/$step/output-requests") \
    > "$RESULTS/$step/benchmark.log" 2>&1
  local rc=$?
  [ $rc = 124 ] && echo "[$step] BENCHMARK TIMEOUT after ${BENCH_TIMEOUT}s"
  echo "[$step] benchmark exit=$rc"; tail -40 "$RESULTS/$step/benchmark.log"
  return $rc
}

CFG_DIR="$RESULTS/configs"; mkdir -p "$CFG_DIR"
declare -A STATUS
for step in $STEPS; do
  echo; echo "################ $step $(date -u +%T) ################"
  case $step in
    static)
      make_config benchmark/multi-model/model_configs/1_gpu_2_model_colocate_static.json "$CFG_DIR/static.json"
      start_server static 30000 "$CFG_DIR/static.json" \
          --disable-cuda-graph --disable-radix-cache --load-format dummy \
        && run_bench static --base-url http://127.0.0.1:30000 --num-models 2 \
             --model-paths model_1 model_2 --exp-name static_baseline --req-rate 10 --seed 42
      ;;
    elastic)
      make_config benchmark/multi-model/model_configs/1_gpu_2_model_colocate_elastic.json "$CFG_DIR/elastic.json"
      start_server elastic 30001 "$CFG_DIR/elastic.json" \
          --disable-cuda-graph --disable-radix-cache --enable-elastic-memory --use-kvcached-v0 \
        && run_bench elastic --base-url http://127.0.0.1:30001 --num-models 2 \
             --model-paths model_1 model_2 --exp-name elastic_memory --enable-elastic-memory \
             --req-rate 10 --seed 42
      ;;
    prism1|prism2)
      # README example 3 (full Prism flags) on 1 or 2 GPUs. 1 GPU: the repo's 1_gpu_2_model_our.json.
      # 2 GPUs: the README's 8_gpu_18_model_our.json restricted to its GPU 0 and 1 placements
      # (3 models per GPU), renamed model_1..model_6 for the benchmark.
      ngpu=${step#prism}
      if [ "$ngpu" = 1 ]; then
        make_config benchmark/multi-model/model_configs/1_gpu_2_model_our.json "$CFG_DIR/$step.json"
      else
        python3 - benchmark/multi-model/model_configs/8_gpu_18_model_our.json "$CFG_DIR/$step.src.json" "$ngpu" <<'PY2'
import json, sys
cfg = [m for m in json.load(open(sys.argv[1]))
       if m["init_placements"][0]["gpu_ids"][0] < int(sys.argv[3])]
cfg.sort(key=lambda m: m["init_placements"][0]["gpu_ids"][0])
for i, m in enumerate(cfg):
    m["model_name"] = f"model_{i + 1}"
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY2
        make_config "$CFG_DIR/$step.src.json" "$CFG_DIR/$step.json"
      fi
      nmod=$(python3 -c "import json;print(len(json.load(open('$CFG_DIR/$step.json'))))")
      models=$(seq -f "model_%g" 1 "$nmod" | tr '\n' ' ')
      python3 -c "import json;[print(' ', m['model_name'], m['model_path'], m['init_placements'][0]['gpu_ids']) for m in json.load(open('$CFG_DIR/$step.json'))]"
      start_server "$step" 30002 "$CFG_DIR/$step.json" \
          --disable-cuda-graph --disable-radix-cache --enable-cpu-share-memory \
          --enable-elastic-memory --use-kvcached-v0 --max-mem-usage 67.28 \
          --enable-gpu-scheduler --enable-controller --policy simple-global \
          --enable-model-service --enable-worker-pool --workers-per-gpu 4 \
          --num-model-service-workers 4 --num-gpus "$ngpu" \
        && run_bench "$step" --base-url http://127.0.0.1:30002 --num-models "$nmod" --num-gpus "$ngpu" \
             --model-paths $models \
             --exp-name "prism_full_${ngpu}gpu" --e2e-benchmark --real-trace ./real_trace.pkl \
             --time-scale 1 --replication 1
      ;;
    cmp_parity|cmp_sweep|cmp_graph)
      # Backend comparison (polyaxon/compare/): same 2-model config (Llama-3.1-8B + Llama-3.2-3B, 20 GB
      # static pools, real weights) for PRISM_BACKEND=sglang and vllm. cmp_graph runs with CUDA graphs
      # (the vLLM backend needs PRISM_VLLM_CUDA_GRAPH=1 and then refuses activate/deactivate).
      cfg="$CFG_DIR/compare.json"; cp polyaxon/configs/compare_2_model.json "$cfg"
      graph=(--disable-cuda-graph); [ "$step" = cmp_graph ] && graph=()
      baseline=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0)
      PRISM_VLLM_CUDA_GRAPH=$([ "$step" = cmp_graph ] && echo 1 || echo 0) \
        start_server "$step" 30004 "$cfg" "${graph[@]}" --disable-radix-cache || { STATUS[$step]=1; continue; }
      case $step in
        cmp_parity)
          python3 polyaxon/compare/parity.py 30004 "$RESULTS/$step/parity.json" \
          && PRISM_GPU_BASELINE_GB=$(python3 -c "print($baseline/1024)") \
             python3 polyaxon/compare/activation.py 30004 "$RESULTS/$step/activation.json" 10 ;;
        *)
          rc=0
          for rate in ${PRISM_SWEEP_RATES:-5 10 20}; do
            run_bench "$step/rate$rate" --base-url http://127.0.0.1:30004 --num-models 2 \
              --model-paths model_1 model_2 --exp-name "${step}_rate$rate" --req-rate "$rate" --seed 42 || rc=1
          done
          [ $rc = 0 ] ;;
      esac
      ;;
    cmp_overhead|tp_overhead)
      # Prism's own overhead: one model behind Prism (static 20 GB pool per rank, eager, no prefix cache)
      # vs. the plain engine with the same settings: `vllm serve` for the vLLM backend, upstream SGLang
      # 0.3.4.post2 (/sgl-workspace/sglang in the SGLang image) for the SGLang backend.
      # cmp_overhead: Llama-3.2-3B (compare config, model_2); tp_overhead: Llama-3.1-8B with TP=2 (2 GPUs).
      if [ "$step" = tp_overhead ]; then
        cfg="$CFG_DIR/$step.json"; cp polyaxon/configs/tp2_1_model.json "$cfg"
        model=model_1; hf=meta-llama/Llama-3.1-8B-Instruct; tp=2; tokens=327680  # 64 KiB/token per rank
      else
        cfg="$CFG_DIR/compare.json"; cp polyaxon/configs/compare_2_model.json "$cfg"
        model=model_2; hf=meta-llama/Llama-3.2-3B-Instruct; tp=1; tokens=187000  # 112 KiB/token
      fi
      start_server "$step" 30004 "$cfg" --disable-cuda-graph --disable-radix-cache || { STATUS[$step]=1; continue; }
      python3 polyaxon/compare/overhead.py prism 30004 $model "$RESULTS/$step/prism.json"; rc=$?
      stop_server
      wait_ports_free 30005 1
      if [ "${PRISM_BACKEND:-sglang}" = vllm ]; then
        ENABLE_KVCACHED=false VLLM_ALLREDUCE_USE_SYMM_MEM=0 VLLM_ALLREDUCE_USE_FLASHINFER=0 \
          VLLM_FLASHINFER_ALLREDUCE_BACKEND=trtllm setsid vllm serve $hf --port 30005 \
          --served-model-name $model --enforce-eager --no-enable-prefix-caching --tensor-parallel-size $tp \
          --kv-cache-memory-bytes $((20 * 1024 * 1024 * 1024)) --gpu-memory-utilization 0.5 \
          --max-num-batched-tokens 8192 > "$RESULTS/$step/engine_serve.log" 2>&1 &
        mode=vllm
      else
        PYTHONPATH=/sgl-workspace/sglang/python setsid python3 -m sglang.launch_server \
          --model-path $hf --port 30005 --disable-cuda-graph --tp $tp \
          --disable-radix-cache --max-total-tokens $tokens --chunked-prefill-size 8192 \
          > "$RESULTS/$step/engine_serve.log" 2>&1 &
        mode=sglang
      fi
      SERVER_PID=$!
      for _ in $(seq 1 120); do curl -sf -o /dev/null http://127.0.0.1:30005/health && break; sleep 5; done
      python3 polyaxon/compare/overhead.py $mode 30005 $model "$RESULTS/$step/engine.json" || rc=1
      [ $rc = 0 ]
      ;;
    swap_static|swap_elastic)
      # vLLM worker-pool core operation: switch one process's engine between models
      # (polyaxon/experiments/engine_swap.py). vLLM backend image only.
      mkdir -p "$RESULTS/$step"; df -h /dev/shm | tail -1
      VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 ENABLE_KVCACHED=$([ "$step" = swap_elastic ] && echo true || echo false) \
        KVCACHED_IPC_NAME="swap_$$" python3 polyaxon/experiments/engine_swap.py \
        "$RESULTS/$step/engine_swap.json" 3 > "$RESULTS/$step/engine_swap.log" 2>&1
      rc=$?; grep -E "^(cold|swap|phases|all outputs)" "$RESULTS/$step/engine_swap.log" | cut -c1-400
      tail -30 "$RESULTS/$step/engine_swap.log" | grep -iE "error|Traceback" -A3 | head -20
      [ $rc = 0 ]
      ;;
    wp_test)
      # Worker pool semantics (polyaxon/test_worker_pool.py): README worker-pool flags without the global
      # controller, so only the test moves models. PRISM_WP_GPUS=2 adds the migration check.
      ngpu=${PRISM_WP_GPUS:-1}
      cp polyaxon/configs/worker_pool_test.json "$CFG_DIR/$step.json"
      start_server "$step" 30006 "$CFG_DIR/$step.json" --disable-cuda-graph --disable-radix-cache \
          --enable-cpu-share-memory --enable-elastic-memory --use-kvcached-v0 --enable-gpu-scheduler \
          --enable-model-service --enable-worker-pool --workers-per-gpu 2 --num-gpus "$ngpu" \
        && { python3 polyaxon/test_worker_pool.py 30006 "$ngpu" 2>&1 | tee "$RESULTS/$step/test_worker_pool.log"; \
             [ "${PIPESTATUS[0]}" = 0 ]; }
      ;;
    wp_tp_test)
      # TP model in the vLLM worker pool (2 GPUs): polyaxon/test_worker_pool_tp.py.
      cp polyaxon/configs/worker_pool_tp_test.json "$CFG_DIR/$step.json"
      start_server "$step" 30008 "$CFG_DIR/$step.json" --disable-cuda-graph --disable-radix-cache \
          --enable-cpu-share-memory --enable-elastic-memory --use-kvcached-v0 --enable-gpu-scheduler \
          --enable-model-service --enable-worker-pool --workers-per-gpu 2 --num-gpus 2 \
        && { python3 polyaxon/test_worker_pool_tp.py 30008 2>&1 | tee "$RESULTS/$step/test_worker_pool_tp.log"; \
             [ "${PIPESTATUS[0]}" = 0 ]; }
      ;;
    tp_switch_static|tp_switch_elastic|tp_sweep)
      # Tensor parallelism (2 GPUs): both models with tp_size=2 on GPUs 0-1 (polyaxon/configs/tp2_2_model.json).
      # tp_switch_*: polyaxon/test_switching.py (GPU 0 memory = rank 0); tp_sweep: synthetic load at 5/10/20 req/s.
      cp polyaxon/configs/tp2_2_model.json "$CFG_DIR/$step.json"
      extra=(); [ "$step" = tp_switch_elastic ] && extra=(--enable-elastic-memory --use-kvcached-v0)
      start_server "$step" 30007 "$CFG_DIR/$step.json" --disable-cuda-graph --disable-radix-cache "${extra[@]}" \
        || { STATUS[$step]=1; continue; }
      if [ "$step" = tp_sweep ]; then
        rc=0
        for rate in ${PRISM_SWEEP_RATES:-5 10 20}; do
          run_bench "$step/rate$rate" --base-url http://127.0.0.1:30007 --num-models 2 \
            --model-paths model_1 model_2 --exp-name "${step}_rate$rate" --req-rate "$rate" --seed 42 || rc=1
        done
        [ $rc = 0 ]
      else
        python3 polyaxon/test_switching.py 30007 $([ "$step" = tp_switch_elastic ] && echo --elastic) \
          2>&1 | tee "$RESULTS/$step/test_switching.log"; [ "${PIPESTATUS[0]}" = 0 ]
      fi
      ;;
    switch_static|switch_elastic)
      # Model switching (activate/deactivate, RECOMPUTE/RETURN preemption, resize) on the static and
      # elastic README configs with real weights: polyaxon/test_switching.py.
      mode=${step#switch_}
      make_config benchmark/multi-model/model_configs/1_gpu_2_model_colocate_$mode.json "$CFG_DIR/$step.json"
      extra=(); [ "$mode" = elastic ] && extra=(--enable-elastic-memory --use-kvcached-v0)
      start_server "$step" 30003 "$CFG_DIR/$step.json" --disable-cuda-graph --disable-radix-cache "${extra[@]}" \
        && { python3 polyaxon/test_switching.py 30003 $([ "$mode" = elastic ] && echo --elastic) \
               2>&1 | tee "$RESULTS/$step/test_switching.log"; [ "${PIPESTATUS[0]}" = 0 ]; }
      ;;
    overload)
      # Example 3 (README Prism flags) on 1 GPU under memory + load overload: 8 models whose weights
      # (~80 GB) exceed the README budget (--max-mem-usage 67.28), 4 of them initially off, and the
      # real trace replayed at PRISM_TIME_SCALES (1 = real time, 0.1 = 10x faster). Fresh server per level.
      # --workers-per-gpu 8 (README: 4): with 4 workers and 4 models initially on, activating a 5th model
      # fails in worker_pool.handle_activate_model ("No idle worker"), the failure is never reported to the
      # global controller (gpu_scheduler.py ~297), which keeps the model ACTIVE and its requests hang.
      cfg=polyaxon/configs/1_gpu_8_model_overload.json
      cp "$cfg" "$CFG_DIR/overload.json"
      profile_missing "$cfg" || { echo "[overload] PROFILING FAILED"; STATUS[$step]=1; stop_server; continue; }
      models=$(seq -f "model_%g" 1 8 | tr '\n' ' ')
      rc=0
      for ts in ${PRISM_TIME_SCALES:-1 0.5 0.25 0.1}; do
        lvl="overload/ts$ts"
        # Trace span is 600 s at 1x; allow that plus 10 min to drain, so a stuck level can't block the rest.
        BENCH_TIMEOUT=$(python3 -c "print(int(600 * $ts + 600))")
        echo "---- $lvl $(date -u +%T)"
        { start_server "$lvl" 30002 "$CFG_DIR/overload.json" \
            --disable-cuda-graph --disable-radix-cache --enable-cpu-share-memory \
            --enable-elastic-memory --use-kvcached-v0 --max-mem-usage 67.28 \
            --enable-gpu-scheduler --enable-controller --policy simple-global \
            --enable-model-service --enable-worker-pool --workers-per-gpu "${PRISM_WORKERS_PER_GPU:-8}" \
            --num-model-service-workers 4 --num-gpus 1 \
          && run_bench "$lvl" --base-url http://127.0.0.1:30002 --num-models 8 --num-gpus 1 \
               --model-paths $models --exp-name "prism_overload_ts$ts" --e2e-benchmark \
               --real-trace ./real_trace.pkl --time-scale "$ts" --replication 1; } || rc=1
        stop_server
      done
      [ $rc = 0 ]
      ;;
    ovl_mem|ovl_phases|ovl_kv|ovl_compute|ovl_trace|ovl_mix)
      # Real overload scenarios on 1 GPU (README example 3 flags, workers-per-gpu = number of models).
      # Load: polyaxon/overload_load.py (open loop, uniform popularity, deadline = duration + drain;
      # requests still pending at the deadline are recorded as unserved). Each level: fresh server and
      # nvidia-smi sampled every second (gpu.csv), so the overload can be checked against the GPU.
      #   ovl_mem     N x PRISM_OVL_MODEL whose weights exceed the GPU, all models sending all the time
      #   ovl_phases  same models in 2 groups taking turns every PRISM_OVL_PHASE s (time sharing)
      #   ovl_kv      4 models that fit, long prompts/outputs: KV demand beyond the free memory
      #   ovl_compute 2 models, sustained rate beyond what the GPU decodes
      #   ovl_trace   8 x PRISM_OVL_MODEL (weights exceed the GPU) under Prism's e2e benchmark trace
      #               (real_trace.pkl, as benchmark.py --e2e-benchmark); levels are time scales (ts<s>)
      #   ovl_mix     two model sizes: 8 x PRISM_OVL_MODEL at the level's rate + 2 x PRISM_OVL_MODEL2 (smaller)
      #               at PRISM_OVL_RATE2 (fewer tokens/s than an 8B, more per GB), 5 + 2 on, ~132 GB of weights.
      #               At most 10 models: 14 workers hang at start-up (kvcached cuMemSetAccess out of memory).
      M="${PRISM_OVL_MODEL:-meta-llama/Llama-3.1-8B-Instruct}"
      M2="${PRISM_OVL_MODEL2:-meta-llama/Llama-3.2-3B-Instruct}"; n2=0; on2=0
      case $step in
        ovl_mem)     n=${PRISM_OVL_N:-10}; on=${PRISM_OVL_ON:-6}; pool=${PRISM_OVL_POOL:-10}
                     rates=${PRISM_OVL_RATES:-0.2 0.5}; dur=${PRISM_OVL_DURATION:-300}; drain=${PRISM_OVL_DRAIN:-300}
                     load="--input-range 256 1024 --output-range 128 512" ;;
        ovl_phases)  n=${PRISM_OVL_N:-10}; on=${PRISM_OVL_ON:-5}; pool=${PRISM_OVL_POOL:-10}
                     rates=${PRISM_OVL_RATES:-0.5}; dur=${PRISM_OVL_DURATION:-600}; drain=${PRISM_OVL_DRAIN:-300}
                     load="--input-range 256 1024 --output-range 128 512 --groups 2 --phase ${PRISM_OVL_PHASE:-150}" ;;
        ovl_kv)      n=${PRISM_OVL_N:-4}; on=$n; pool=${PRISM_OVL_POOL:-40}
                     rates=${PRISM_OVL_RATES:-0.25 0.5 1}; dur=${PRISM_OVL_DURATION:-180}; drain=${PRISM_OVL_DRAIN:-600}
                     load="--input-range 2048 4096 --output-range 1024 2048" ;;
        ovl_compute) n=${PRISM_OVL_N:-2}; on=$n; pool=${PRISM_OVL_POOL:-30}  # pool: KV cap per model (GB)
                     rates=${PRISM_OVL_RATES:-5 12.5 25 50}; dur=${PRISM_OVL_DURATION:-120}; drain=${PRISM_OVL_DRAIN:-300}
                     load="--input-range 256 768 --output-range 128 384" ;;
        ovl_trace)   n=${PRISM_OVL_N:-8}; on=${PRISM_OVL_ON:-6}; pool=${PRISM_OVL_POOL:-10}
                     rates=${PRISM_OVL_RATES:-1 0.5 0.25}; dur=; drain=${PRISM_OVL_DRAIN:-300}
                     load="--real-trace benchmark/multi-model/real_trace.pkl" ;;
        ovl_mix)     n=${PRISM_OVL_N:-8}; on=${PRISM_OVL_ON:-5}; n2=${PRISM_OVL_N2:-2}; on2=${PRISM_OVL_ON2:-2}
                     pool=${PRISM_OVL_POOL:-10}
                     rates=${PRISM_OVL_RATES:-0.2}; dur=${PRISM_OVL_DURATION:-300}; drain=${PRISM_OVL_DRAIN:-300}
                     load="--input-range 256 1024 --output-range 128 512 --model-rates $(for i in $(seq $((n + 1)) $((n + n2))); do printf 'model_%s=%s ' "$i" "${PRISM_OVL_RATE2:-0.12}"; done)" ;;
      esac
      # PRISM_OVL_LOAD replaces the step's load arguments (lengths, --cv, --groups) to vary the workload.
      load="${PRISM_OVL_LOAD:-$load}"
      python3 - "$CFG_DIR/$step.json" "$M" "$n" "$on" "$pool" "$M2" "$n2" "$on2" <<'PY2'
import json, sys
out, path, n, on, pool = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
path2, n2, on2 = sys.argv[6], int(sys.argv[7]), int(sys.argv[8])  # ovl_mix: a second, smaller model
models = [(path, i <= on) for i in range(1, n + 1)] + [(path2, i <= on2) for i in range(1, n2 + 1)]
cfg = [{"model_name": f"model_{i}", "model_path": p, "tokenizer_path": p, "tp_size": 1,
        "init_placements": [{"gpu_ids": [0], "on": o, "max_memory_pool_size": pool}]}
       for i, (p, o) in enumerate(models, 1)]
json.dump(cfg, open(out, "w"), indent=2)
print(f"config {out}: {n} x {path} ({on} on)" + (f" + {n2} x {path2} ({on2} on)" if n2 else "") + f", pool {pool} GB")
PY2
      profile_missing "$CFG_DIR/$step.json" || { echo "[$step] PROFILING FAILED"; STATUS[$step]=1; continue; }
      n=$((n + n2))
      models=$(seq -f "model_%g" 1 "$n" | tr '\n' ' ')
      rc=0
      for rate in $rates; do
        if [ "$step" = ovl_trace ]; then  # level = time scale; the window is the trace span x scale
          lvl="$step/ts$rate"; dur=$(python3 -c "print(600 * $rate)"); level=(--time-scale "$rate")
        else
          lvl="$step/rate$rate"; level=(--rate "$rate" --duration "$dur")
        fi
        echo "---- $lvl $(date -u +%T)"
        mkdir -p "$RESULTS/$lvl"
        if start_server "$lvl" 30002 "$CFG_DIR/$step.json" \
            --disable-cuda-graph --disable-radix-cache --enable-cpu-share-memory \
            --enable-elastic-memory --use-kvcached-v0 --max-mem-usage "${PRISM_OVL_MAX_MEM:-67.28}" \
            --enable-gpu-scheduler --enable-controller --policy simple-global \
            --enable-model-service --enable-worker-pool --workers-per-gpu "$n" \
            --num-model-service-workers 4 --num-gpus 1; then
          nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,nounits -lms 1000 \
            > "$RESULTS/$lvl/gpu.csv" 2>/dev/null &
          SMI_PID=$!
          timeout -k 30 $((${dur%.*} + ${drain%.*} + 120)) python3 polyaxon/overload_load.py \
            --base-url http://127.0.0.1:30002 --models $models "${level[@]}" --drain "$drain" \
            $load --slo-ttft "${PRISM_OVL_SLO_TTFT:-1.0}" --slo-tpot "${PRISM_OVL_SLO_TPOT:-0.1}" \
            --out "$RESULTS/$lvl" > "$RESULTS/$lvl/load.log" 2>&1 || rc=1
          kill $SMI_PID 2>/dev/null
          echo "[$lvl] load exit, $(grep -c . "$RESULTS/$lvl/gpu.csv") GPU samples"; tail -n "$((n + 2))" "$RESULTS/$lvl/load.log"
        else
          rc=1
        fi
        stop_server
      done
      [ $rc = 0 ]
      ;;
    *) echo "unknown step $step"; false ;;
  esac
  STATUS[$step]=$?
  stop_server
done

echo; echo "################ summary ################"
for step in $STEPS; do echo "$step: exit=${STATUS[$step]}"; done
echo "end $(date -u +%FT%TZ)"
