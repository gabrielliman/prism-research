# Prism on vLLM (`--engine-backend vllm`)

Prism's control plane (HTTP server, request handler, Redis queues, GPU scheduler, global controller and
policies) is unchanged. Each model instance is served by an **unmodified vLLM engine** (v0.30.0) behind an
adapter process (`engine_adapter.py`) that speaks the protocol of the Prism-modified SGLang scheduler.
Elastic KV memory uses **upstream kvcached** (v0.1.6) instead of the `prism/shm` branch.

```
python3 -m sglang.launch_multi_model_server --engine-backend vllm \
  --model-config-file ./model_configs/1_gpu_2_model_colocate_elastic.json \
  --port 30001 --disable-cuda-graph --disable-radix-cache --enable-elastic-memory
```

Environment: `docker/prism-vllm` (kvcached's `kvcached-vllm` image + `pip install -e "python[vllm_backend]"`).
The SGLang backend still needs the original environment (`docker/prism`, SGLang 0.3.4 / vLLM 0.6.3); the two
cannot share one Python environment.

## Design choices

| Decision | Choice | Alternatives considered |
| --- | --- | --- |
| Integration | Adapter around an unmodified vLLM engine | Fork vLLM's scheduler/worker/model runner |
| Versions | vLLM 0.30.0 + kvcached 0.1.6 (kvcached's tested pair, official image) | vLLM 0.31; vLLM 0.8.4 + old kvcached patch |
| Activation | Own weight offload in a vLLM worker extension (pinned CPU copy, like `SingleModelRunner`) | vLLM sleep mode (shares cuMem with kvcached, untested); restarting the engine |
| Worker pool | Not supported in this version | Sleeping engine per (model, GPU); rebuilding an engine per activation |
| Code layout | Selectable backend (`--engine-backend {sglang,vllm}`), SGLang path untouched | Replace SGLang |
| Engine loop | Synchronous `LLMEngine.step()` with in-process EngineCore | `AsyncLLM` |
| RECOMPUTE preemption | Local continuation (prompt + generated tokens resubmitted on activation) | Requeue from scratch |

## Component mapping

| Prism (SGLang backend) | vLLM backend | Status |
| --- | --- | --- |
| `Scheduler` event loop (`event_loop_normal`) | `VllmEngineAdapter.event_loop`: control requests, Redis pull, `engine.step()` | Adapted |
| `recv_generation_requests` (fetch count from free KV / avg input len) | Same formula; free KV = vLLM block pool free blocks × block size | Adapted |
| `_tokenize` + `handle_generate_request` | `_submit`: `tokenizer.encode`, SGLang→vLLM sampling params (`sampling.py`), context-length cap | Adapted |
| `get_new_batch_prefill` / `update_running_batch` / `run_batch` (batching, chunked prefill, retract) | vLLM's own scheduler | Replaced (not reproduced) |
| `BatchRunReq` to controller | Sent for requests whose `num_computed_tokens` became > 0 in a step | Adapted (step granularity) |
| `BatchRetractDecodeReq` (decode OOM retract) | Sent when vLLM's `num_preemptions` of a request grows | Adapted (detection, not control) |
| `_should_abort_req` / `abort_exceed_slo_reqs` (`--abort-exceed-slos`) | Same rule on requests not yet scheduled | Adapted |
| `stream_output` + `DetokenizerManager` | `_send_outputs`: vLLM detokenizes, adapter sends `BatchStrOut` straight to the request handler | Adapted (no detokenizer process) |
| meta_info timestamps (arrival, out_queue, prefill_finish, decode, finish) | Taken at step boundaries in the adapter | Adapted |
| `UpdateModelTput` (1 s thread) | Sent from the loop every ≥1 s | Adapted |
| `handle_activate_request` | Reload pinned weights (`prism_load_weights`), restore KV (static) or raise kvcached limit (elastic), resubmit RECOMPUTE continuations | Adapted |
| `handle_activate_request` with another `gpu_id` (TP=1 migration) | A vLLM engine is bound to its device | **Not adapted** (returns `success=False`) |
| `handle_deactivate_request`, `preempt=False` | Step until all requests finish | Adapted |
| `PreemptMode.RETURN` | Abort in vLLM and return the text so far with `finish_reason=length` | Adapted (waiting requests are not prefilled first) |
| `PreemptMode.RECOMPUTE` | Abort in vLLM, keep prompt+output, resubmit as continuation on activation | Adapted (output stitched as text) |
| `evict_waiting_requests` | Unscheduled requests aborted and sent back to the frontend Redis queue | Adapted |
| `resize_mem_pool` (elastic) | `kvcached.control.set_instance_memory_limit` in the worker | Adapted |
| `resize_mem_pool` / activation `memory_pool_size` (static) | vLLM's KV block count is fixed at start-up | **Not adapted** (ignored with a warning; SGLang raised) |
| `MHATokenToKVPool` + kvcached `prism/shm` | vLLM KV cache + upstream kvcached autopatch, `KVCACHED_IPC_NAME=ipc_{gpu}_{model}_{user}` | Adapted |
| KV usage in shm for `ResourceManager` | kvcached's segment (`[total, used, prealloc]`); `ResourceManager` reads field 1 when the segment has 3 fields | Adapted |
| Static memory pool size (`max_memory_pool_size`) | `kv_cache_memory_bytes` | Adapted |
| `ReqToTokenPool` | vLLM block tables (scheduler side) | Replaced (`req_to_token_pool_memory` reported as 0) |
| `on: false` placements | Engine built, then weights offloaded and KV released | Adapted (start-up needs the GPU memory once) |
| Parallel engine start-up | Engines on one GPU start one at a time (file lock): vLLM profiles whole-device memory | Changed |
| `get_memory_usage` / `get_memory_pool_size` / flush cache / abort / profile | Mapped to vLLM equivalents | Adapted |
| `update_weights` | — | **Not adapted** (returns failure) |
| CUDA graphs | Always `enforce_eager` (re-pointed weights would invalidate graphs) | Restricted |
| Worker pool (`WorkerPoolModelRunner`, `RequestHandlerWorkerPool`, `--workers-per-gpu`) | — | **Not adapted** (rejected at start-up) |
| Model service / CPU shared-memory weights (`model_sevice.py`, `--enable-cpu-share-memory`) | Each engine keeps its own pinned CPU copy | **Not adapted** (rejected at start-up) |
| `--async-loading` | — | **Not adapted** (rejected) |
| `--use-kvcached-v0` | Ignored with a warning (upstream kvcached is used) | Replaced |
| Overlap schedule, LoRA, double sparsity, data parallelism, multi-node | — | **Not adapted** (rejected) |
| Logprobs | Not supported by Prism's multi-model request handler either | Unchanged |
| Structured outputs (`regex`, `json_schema`) | vLLM `StructuredOutputsParams` | Adapted (untested) |
| `profile_model_info.py` (uses vLLM 0.6 loader) | `model_info.json` must already list the models | **Not adapted** |

## Changes outside the backend

* `multi_model_server.py`: `--engine-backend vllm` launches `run_vllm_engine_process` (one process per
  instance, kvcached environment set before spawn); SGLang runtime imports are lazy; unsupported flags are
  rejected; **bug fix**: `launch_model_engines` returned `init_placements=None`, so `--enable-gpu-scheduler`
  without `--enable-worker-pool` crashed for both backends.
* `scheduling/gpu/resource_manager.py`: reads kvcached's 3-field usage segment; imports the old kvcached
  only in worker-pool mode.
* `srt/managers/io_struct.py`, `srt/utils.py`: import guards so the control plane loads without SGLang
  0.3.4's runtime dependencies (outlines, triton < 3.2).
* `srt/server_args.py`, `multi_model_server_args.py`: `engine_backend` argument.

## Validation (Polyaxon, 1× H200, image `gabrielliman/prism:vllm0.30-kvcached0.1.6`)

| Step (`polyaxon/run_examples.sh`, `PRISM_BACKEND=vllm`) | Result |
| --- | --- |
| `static` (README ex. 1, 2× Llama-3.1-8B, `--load-format dummy`) | 145/145 requests per model; TTFT ≈ 32 ms, TPOT ≈ 15 ms |
| `elastic` (README ex. 2, kvcached) | benchmark completes, 0 aborted |
| `prism1` (README ex. 3 flags minus worker pool/model service, 2× Llama-3.2-3B) | 318/318 requests; GPU scheduler admission and controller idle deactivation working |
| `switch_static` / `switch_elastic` (`polyaxon/test_switching.py`, 2× Llama-3.1-8B) | activation 0.29 s, deactivation frees weights + KV (elastic: down to one page per layer), greedy output identical after reactivation, RETURN and RECOMPUTE preemption, resize and sized activation |

RECOMPUTE resumes seamlessly at the splice; the full greedy text can diverge later (char 997 of 1806 in
the test) because recomputing the KV in one prefill is not bit-identical to building it during decode.
