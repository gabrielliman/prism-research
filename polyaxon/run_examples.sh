#!/bin/bash
# Runs the README examples on Polyaxon (see prism_examples.yaml / submit.sh).
# Steps (PRISM_STEPS, default "static elastic prism1"; prism2 needs a 2-GPU job):
#   static  - README example 1: 2 models colocated, static memory, --load-format dummy
#   elastic - README example 2: 2 models colocated, elastic memory (kvcached)
#   prism1  - README example 3 (full Prism flags) on 1 GPU: 1_gpu_2_model_our.json
#   prism2  - README example 3 on 2 GPUs: 8_gpu_18_model_our.json limited to GPUs 0-1 (6 models)
#   overload - example 3 on 1 GPU, 8 models over the memory budget, trace at PRISM_TIME_SCALES
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
STEPS="${PRISM_STEPS:-static elastic prism1}"
STARTUP_TIMEOUT="${PRISM_STARTUP_TIMEOUT:-1200}"
echo "start $(date -u +%FT%TZ) steps: $STEPS  backend: ${PRISM_BACKEND:-sglang}  results: $RESULTS"

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
# python/sglang/multi_model/utils/model_info.json (weights size + KV cell size). Profile the missing
# ones with that directory's profile_model_info.py functions (its __main__ has a fixed model list and
# rewrites the file) and add them to this job's uploaded copy only.
profile_missing() {
  if [ "${PRISM_BACKEND:-sglang}" = vllm ]; then
    # profile_model_info.py needs SGLang 0.3.4's vLLM; estimate from the checkpoint instead.
    python3 -m sglang.multi_model.utils.estimate_model_info --write \
      $(python3 -c "import json;print(' '.join(sorted({m['model_path'] for m in json.load(open('$ROOT/$1'))})))")
    return
  fi
  (cd python/sglang/multi_model/utils && python3 - "$ROOT/$1" <<'PY2'
import json, sys
import profile_model_info as p
cfg = json.load(open(sys.argv[1]))
info = json.load(open("model_info.json"))
missing = sorted({m["model_path"] for m in cfg} - set(info))
print("model_info.json missing:", missing or "none")
if missing:
    p.init_torch_distributed()
    for path in missing:
        p.clean_up()
        size, dtype = p.load_model(path)
        info[path] = {"model_size": size, "cell_size": p.get_cell_size(path, dtype)}
        print("profiled", path, info[path])
    json.dump(info, open("model_info.json", "w"))
PY2
  )
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
# --engine-backend vllm, dropping the README flags that backend does not implement (worker pool, model
# service, CPU shared-memory weights; --use-kvcached-v0 is replaced by upstream kvcached).
backend_args() {
  [ "${PRISM_BACKEND:-sglang}" = vllm ] || { printf '%s\n' "$@"; return; }
  echo --engine-backend; echo vllm
  while [ $# -gt 0 ]; do
    case $1 in
      --enable-cpu-share-memory|--enable-model-service|--enable-worker-pool|--use-kvcached-v0) ;;
      --workers-per-gpu|--num-model-service-workers) shift ;;
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
    *) echo "unknown step $step"; false ;;
  esac
  STATUS[$step]=$?
  stop_server
done

echo; echo "################ summary ################"
for step in $STEPS; do echo "$step: exit=${STATUS[$step]}"; done
echo "end $(date -u +%FT%TZ)"
