"""A Prism model instance backed by an unmodified vLLM engine.

This process replaces, for one model instance, the processes the SGLang backend launches in
multi_model_server.launch_engine: the Scheduler (sglang/srt/managers/scheduler.py) with its TP worker and
model runner, and the DetokenizerManager. It keeps their protocol, so the rest of Prism is unchanged:

* generation requests are pulled from the Redis backend queue `{backend prefix}:{model}` with the same
  KV-aware fetch count as Scheduler.recv_generation_requests;
* control requests (activate, deactivate, resize, memory usage, abort, flush, profile) arrive on the
  scheduler ZMQ socket and are answered to the request handler (and, for activate/deactivate, to the GPU
  scheduler through Redis);
* outputs are sent to the request handler as BatchStrOut with the same meta_info (timestamps used by the
  benchmark), BatchRunReq / BatchRetractDecodeReq go to the global controller, and UpdateModelTput reports
  the token throughput every second;
* the KV usage is published in shared memory `ipc_{gpu}_{model}_{user}` for the GPU scheduler's
  ResourceManager (by kvcached itself with elastic memory).

vLLM runs in this process (in-process EngineCore, VLLM_ENABLE_V1_MULTIPROCESSING=0) and is driven with
LLMEngine.step(), so control requests are handled between engine steps exactly like in Prism's scheduler
loop. The engine's own scheduler is only read (waiting/running requests, free KV blocks), never modified.
"""

import fcntl
import getpass
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from types import SimpleNamespace
from typing import Dict, List, Optional

import zmq

from sglang.srt.managers.io_struct import (
    AbortReq,
    ActivateReqInput,
    ActivateReqOutput,
    BatchRetractDecodeReq,
    BatchRunReq,
    BatchStrOut,
    DeactivateReqInput,
    DeactivateReqOutput,
    FlushCacheReq,
    GenerateReqInput,
    GetMemoryUsageReq,
    GetMemoryUsageReqOutput,
    GetMemPoolSizeReq,
    GetMemPoolSizeReqOutput,
    MemoryUsage,
    PreemptMode,
    ProfileReq,
    ResizeMemPoolReqInput,
    UpdateModelTput,
    UpdateWeightReqInput,
    UpdateWeightReqOutput,
)
from sglang.srt.redis_utils import RedisClient
from sglang.srt.server_args import PortArgs, ServerArgs
from sglang.srt.utils import change_logger_format, configure_logger
from sglang.utils import get_exception_traceback

logger = logging.getLogger(__name__)

GB = 1 << 30
CONTINUATION_ATTR = "prism_continuation"
CONTINUATION_FIELDS = (
    "prompt_len", "prompt_ids", "prefix_token_ids", "prefix_text", "out_queue_timestamp",
    "prefill_finish_timestamp", "decode_timestamps", "num_cached_tokens", "num_preemptions",
)
WORKER_EXTENSION = "sglang.multi_model.vllm_backend.worker_extension.PrismWorkerExtension"


@dataclass
class _Req:
    """Adapter-side state of one Prism request (Prism keeps the equivalent in schedule_batch.Req)."""

    obj: GenerateReqInput
    prompt_len: int
    internal_id: Optional[str] = None  # vLLM's request id for the current submission
    out_queue_timestamp: Optional[float] = None
    prefill_finish_timestamp: Optional[float] = None
    decode_timestamps: List[float] = field(default_factory=list)
    num_cached_tokens: int = 0
    # Tokens of the current submission already seen, and its prompt length.
    num_seen: int = 0
    submitted_prompt_len: int = 0
    # Output produced before a RECOMPUTE preemption; the request is resubmitted as a continuation.
    prefix_token_ids: List[int] = field(default_factory=list)
    prefix_text: str = ""
    text: str = ""
    token_ids: List[int] = field(default_factory=list)
    num_preemptions: int = 0
    prompt_ids: Optional[List[int]] = None

    @property
    def rid(self) -> str:
        return self.obj.rid

    @property
    def num_output_tokens(self) -> int:
        return len(self.prefix_token_ids) + len(self.token_ids)


class VllmEngineAdapter:
    def __init__(self, server_args: ServerArgs, port_args: PortArgs, gpu_ids: List[int]):
        self.server_args = server_args
        self.port_args = port_args
        self.gpu_ids = gpu_ids
        self.gpu_id = gpu_ids[0]
        self.model_name = server_args.model_name
        self.instance_idx = getattr(server_args, "instance_idx", 0)
        self.enable_elastic_memory = server_args.enable_elastic_memory
        self.ipc_name = f"ipc_{self.gpu_id}_{self.model_name}_{getpass.getuser()}"
        self.cuda_graphs = (
            os.environ.get("PRISM_VLLM_CUDA_GRAPH") == "1" and not server_args.disable_cuda_graph
        )

        self._init_ipc()
        self._init_engine()
        self._init_state()
        self.active = True

        if self.enable_elastic_memory:
            self.kv_limit_bytes = self._initial_kv_limit_bytes()
            self._set_kv_limit(self.kv_limit_bytes)
        if not server_args.on:
            self._release_gpu_memory()
            self.active = False

    # ------------------------------------------------------------------ init
    def _init_state(self):
        self.reqs: Dict[str, _Req] = {}  # Prism rid -> request in vLLM
        self.continuations: List[_Req] = []  # retracted with RECOMPUTE, resubmitted on activation
        self.decode_forward_ct = 0
        self.total_input_len = 0
        self.num_received_requests = 0
        self.token_count = 0
        self.prefill_token_count = 0
        self.decode_token_count = 0
        self.last_tput_update_time = time.time()
        self.kv_limit_revision = 0

    def _init_ipc(self):
        context = zmq.Context(3)
        self.recv_from_request_handler = context.socket(zmq.PULL)
        self.recv_from_request_handler.bind(f"ipc://{self.port_args.scheduler_input_ipc_name}")
        # The SGLang scheduler sends its outputs through the detokenizer process; vLLM detokenizes itself,
        # so the adapter sends them to the request handler directly.
        self.send_to_request_handler = context.socket(zmq.PUSH)
        self.send_to_request_handler.connect(f"ipc://{self.port_args.request_handler_ipc_name}")
        if self.port_args.controller_ipc_name:
            self.send_to_controller = context.socket(zmq.PUSH)
            self.send_to_controller.connect(f"ipc://{self.port_args.controller_ipc_name}")
        else:
            self.send_to_controller = SimpleNamespace(send_pyobj=lambda x: None)
        self.redis_client = RedisClient(
            self.server_args.redis_host, self.server_args.redis_port, self.server_args.redis_db
        )
        # ResourceManager reads the KV bytes in use from this segment. With elastic memory kvcached owns
        # it (KVCACHED_IPC_NAME); otherwise publish 0 like the SGLang engine does with static memory.
        self.shm = None
        if not self.enable_elastic_memory:
            try:
                old = shared_memory.SharedMemory(name=self.ipc_name)
                old.close()
                old.unlink()
            except FileNotFoundError:
                pass
            self.shm = shared_memory.SharedMemory(create=True, size=8, name=self.ipc_name)

    def _gpu_locks(self):
        """Engines on the same GPU start one at a time: vLLM profiles memory with whole-device free memory."""
        locks = []
        for gpu in sorted(self.gpu_ids):
            f = open(f"/tmp/prism_vllm_gpu{gpu}_{getpass.getuser()}.lock", "w")
            fcntl.flock(f, fcntl.LOCK_EX)
            locks.append(f)
        return locks

    def _gpu_free_total(self):
        """Free and total memory of this instance's GPUs (the smallest free across TP ranks), read with
        nvidia-smi: with TP > 1 the model runs in vLLM's worker processes and this process must not
        create a CUDA context of its own."""
        import subprocess

        ids = os.environ.get("PRISM_PHYSICAL_GPUS", "").split(",")
        try:
            rows = []
            for i in ids:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits",
                     "-i", i], timeout=30,
                ).decode().split(",")
                rows.append((int(out[0]) * (1 << 20), int(out[1]) * (1 << 20)))
            return min(f for f, _ in rows), min(t for _, t in rows)
        except Exception as e:
            logger.warning(f"nvidia-smi query failed ({e}); using torch.cuda.mem_get_info")
            import torch

            return torch.cuda.mem_get_info(0)

    def _engine_args(self):
        from vllm import EngineArgs

        sa = self.server_args
        free, total = self._gpu_free_total()
        if self.enable_elastic_memory:
            # kvcached: gpu_memory_utilization only bounds the virtual KV capacity; the physical KV is
            # limited per instance (max_memory_pool_size) through kvcached's memory limit.
            util = sa.max_mem_usage * GB / total if sa.max_mem_usage else sa.mem_fraction_static
            kv_cache_memory_bytes = None
        elif sa.max_memory_pool_size:
            # Static pool of the configured size, like SingleModelRunner._get_init_memory_pool_size.
            kv_cache_memory_bytes = int(sa.max_memory_pool_size * GB)
            # vLLM refuses to start when free memory < utilization * total, even with an explicit KV size.
            util = max(0.05, 0.98 * free / total)
        else:
            # Prism: max_mem_usage (or the free memory * mem_fraction_static) for weights + KV.
            budget = sa.max_mem_usage * GB if sa.max_mem_usage else free * sa.mem_fraction_static
            util = min(budget, 0.98 * free) / total
            kv_cache_memory_bytes = None

        if self.cuda_graphs:
            logger.warning(
                "PRISM_VLLM_CUDA_GRAPH=1: CUDA graphs enabled for measurement only; activate/deactivate "
                "are refused because re-allocated weights would invalidate the captured graphs."
            )
        elif not sa.disable_cuda_graph:
            logger.warning(
                "The vLLM backend runs with enforce_eager: activation re-allocates the weights, "
                "which would invalidate captured CUDA graphs."
            )
        return EngineArgs(
            model=sa.model_path,
            tokenizer=sa.tokenizer_path,
            tokenizer_mode=sa.tokenizer_mode,
            trust_remote_code=sa.trust_remote_code,
            dtype=sa.dtype,
            kv_cache_dtype=sa.kv_cache_dtype,
            quantization=sa.quantization,
            load_format=sa.load_format,
            seed=sa.random_seed,
            # Prism caps a request at min(context length, KV pool tokens) (TpModelWorker.update_memory_info);
            # vLLM instead refuses to start unless one full-context sequence fits. -1 makes vLLM fit the
            # context length to the KV cache.
            max_model_len=sa.context_length or -1,
            tensor_parallel_size=sa.tp_size,
            gpu_memory_utilization=util,
            kv_cache_memory_bytes=kv_cache_memory_bytes,
            enforce_eager=not self.cuda_graphs,
            enable_prefix_caching=not sa.disable_radix_cache,
            max_num_seqs=sa.max_running_requests,
            max_num_batched_tokens=sa.chunked_prefill_size or sa.max_prefill_tokens,
            disable_custom_all_reduce=sa.disable_custom_all_reduce,
            async_scheduling=False,
            disable_log_stats=True,
            worker_extension_cls=WORKER_EXTENSION,
        )

    def _init_engine(self):
        from vllm import LLMEngine

        locks = self._gpu_locks()
        try:
            tic = time.perf_counter()
            self.engine = LLMEngine.from_engine_args(self._engine_args())
            logger.info(f"vLLM engine created in {time.perf_counter() - tic:.2f}s")
        finally:
            for f in locks:
                f.close()
        self._bind_engine()
        self.weights_bytes = self._rpc("prism_snapshot_weights")
        logger.info(
            f"max_total_num_tokens={self.max_total_num_tokens}, max_model_len={self.max_model_len}, "
            f"weights={self.weights_bytes / GB:.2f} GB"
        )

    def _bind_engine(self):
        core = self.engine.engine_core.engine_core
        self.vllm_scheduler = core.scheduler
        cache_config = self.engine.vllm_config.cache_config
        self.block_size = cache_config.block_size
        self.num_gpu_blocks = cache_config.num_gpu_blocks
        self.max_total_num_tokens = self.num_gpu_blocks * self.block_size
        self.max_model_len = self.engine.model_config.max_model_len

    def _rpc(self, method: str, *args):
        """Call the worker extension on every TP rank and return rank 0's result."""
        return self.engine.collective_rpc(method, args=args)[0]

    # --------------------------------------------------------------- memory
    def _initial_kv_limit_bytes(self) -> Optional[int]:
        if self.server_args.max_memory_pool_size:
            return int(self.server_args.max_memory_pool_size * GB)
        return None

    def _set_kv_limit(self, limit_bytes: Optional[int]):
        if limit_bytes is None:
            limit_bytes = 1 << 62  # no limit: kvcached caps it at the virtual capacity
        self.kv_limit_revision += 1
        result = self._rpc("prism_set_kv_limit", int(limit_bytes), self.kv_limit_revision)
        logger.info(
            f"kvcached limit {limit_bytes / GB:.2f} GB (revision {self.kv_limit_revision}): "
            f"{result.get('status')} {result.get('reason') or ''}"
        )
        return result.get("status") in ("applied", "deferred")

    def _kv_used_bytes(self) -> int:
        if getattr(self, "engine", None) is None:
            return 0
        if self.enable_elastic_memory:
            return self._rpc("prism_kv_mapped_bytes")
        return self._rpc("prism_kv_bytes") if self.active else 0

    def get_memory_usage(self) -> MemoryUsage:
        kv = self._kv_used_bytes() / GB
        weights = self.weights_bytes / GB
        return MemoryUsage(
            total_used_memory=(weights if self.active else 0) + kv,
            model_weights_memory=weights,
            memory_pool_memory=kv,
            req_to_token_pool_memory=0.0,  # vLLM keeps block tables in the scheduler, not a GPU pool
            token_to_kv_pool_memory=kv,
        )

    def _release_gpu_memory(self):
        tic = time.perf_counter()
        self.engine.reset_prefix_cache()
        if self.enable_elastic_memory:
            self._set_kv_limit(self._rpc("prism_min_kv_limit"))
            self._rpc("prism_trim_kv")
        else:
            self._rpc("prism_release_kv")
        self._rpc("prism_offload_weights")
        logger.info(f"GPU memory released in {time.perf_counter() - tic:.4f}s")

    def _restore_gpu_memory(self, memory_pool_size: Optional[float]):
        tic = time.perf_counter()
        self._rpc("prism_load_weights")
        if self.enable_elastic_memory:
            if memory_pool_size is not None:
                self.kv_limit_bytes = int(memory_pool_size * GB)
            self._set_kv_limit(self.kv_limit_bytes)
        else:
            if memory_pool_size is not None:
                logger.warning(
                    "Static memory: the KV pool keeps its initial size; memory_pool_size is ignored."
                )
            self._rpc("prism_restore_kv")
        logger.info(f"GPU memory restored in {time.perf_counter() - tic:.4f}s")

    # ---------------------------------------------------------------- loop
    def event_loop(self):
        while True:
            self.process_control_requests(self.recv_control_requests())
            if self.active:
                self.process_generation_requests(self.recv_generation_requests())
                self.abort_exceed_slo_reqs()
                if self.engine.has_unfinished_requests():
                    self.step()
                else:
                    time.sleep(0.001)
                self.maybe_send_token_tput()
            else:
                time.sleep(0.001)

    def recv_control_requests(self):
        reqs = []
        while True:
            try:
                reqs.append(self.recv_from_request_handler.recv_pyobj(zmq.NOBLOCK))
            except zmq.ZMQError:
                return reqs

    @property
    def avg_input_len(self):
        if self.num_received_requests <= 1:
            return 1024
        return self.total_input_len / self.num_received_requests

    def _num_waiting(self) -> int:
        return sum(1 for r in self.reqs.values() if r.out_queue_timestamp is None)

    def recv_generation_requests(self) -> List[GenerateReqInput]:
        # Same fetch count as Scheduler.recv_generation_requests: only pull what the free KV can prefill.
        free_tokens = self.vllm_scheduler.kv_cache_manager.block_pool.get_num_free_blocks() * self.block_size
        remain = min(
            free_tokens,
            self.server_args.max_prefill_tokens or 16384,
            self.server_args.chunked_prefill_size or 8192,
        )
        max_fetch_count = int(remain // self.avg_input_len) + 1 - self._num_waiting()
        if max_fetch_count <= 0:
            return []
        return self.redis_client.recv_pyobj_non_block(
            key=f"{self.server_args.backend_generate_request_key_prefix}:{self.model_name}",
            count=max_fetch_count,
        )

    def process_generation_requests(self, objs: List[GenerateReqInput]):
        for obj in objs:
            assert isinstance(obj, GenerateReqInput)
            assert obj.image_data is None, "Image inputs are not supported."
            prompt_len = len(obj.input_ids) if obj.input_ids is not None else 0
            req = _Req(obj=obj, prompt_len=prompt_len)
            # A request preempted with RECOMPUTE by a worker-pool slot comes back through Redis with its
            # progress (VllmWorkerSlot._retract_running_requests); continue it instead of restarting.
            for k, v in (getattr(obj, CONTINUATION_ATTR, None) or {}).items():
                setattr(req, k, v)
            self.num_received_requests += 1
            self._submit(req)

    def _submit(self, req: _Req):
        from sglang.multi_model.vllm_backend.sampling import to_vllm_sampling_params

        obj = req.obj
        try:
            # Tokenize here like Scheduler._tokenize (tokenizer.encode); a RECOMPUTE continuation is the
            # prompt + the tokens generated before the preemption.
            prompt = {"prompt_token_ids": list(self._prompt_ids(req)) + req.prefix_token_ids}
            prompt_len = len(prompt["prompt_token_ids"])
            if not req.prefix_token_ids:
                req.prompt_len = prompt_len
                self.total_input_len += prompt_len
            sampling = dict(obj.sampling_params or {})
            if req.prefix_token_ids:
                done = len(req.prefix_token_ids)
                sampling["max_new_tokens"] = max(sampling.get("max_new_tokens", 128) - done, 1)
                sampling["min_new_tokens"] = max(sampling.get("min_new_tokens", 0) - done, 0)
            params = to_vllm_sampling_params(sampling, self.max_model_len, prompt_len)
            req.submitted_prompt_len = prompt_len
            req.num_seen = 0
            req.text, req.token_ids = "", []
            req.internal_id = self.engine.add_request(
                obj.rid, prompt, params, arrival_time=obj.arrival_time
            )
        except Exception as e:
            # The SGLang scheduler raises in _validate_input_length; answer with an abort instead.
            logger.error(f"Request {obj.rid} rejected: {e}")
            self._send_outputs([req], [{"type": "abort", "message": str(e)}])
            return
        self.reqs[obj.rid] = req

    def _prompt_ids(self, req: _Req) -> List[int]:
        if req.obj.input_ids is not None:
            return req.obj.input_ids
        if req.prompt_ids is None:
            req.prompt_ids = self.engine.get_tokenizer().encode(req.obj.text)
        return req.prompt_ids

    def _sched_req(self, req: _Req):
        return self.vllm_scheduler.requests.get(req.internal_id)

    def _forget(self, req: _Req):
        self.reqs.pop(req.rid, None)

    def abort_exceed_slo_reqs(self):
        if not self.server_args.abort_exceed_slos:
            return
        # Scheduler._should_abort_req, applied to requests that have not been scheduled yet.
        now = time.time()
        abort = [
            r
            for r in self.reqs.values()
            if r.out_queue_timestamp is None
            and r.obj.slo is not None
            and now + 0.5 - r.obj.arrival_time > r.obj.slo
        ]
        if abort:
            self.engine.abort_request([r.rid for r in abort])
            for r in abort:
                self._forget(r)
            self._send_outputs(abort, [{"type": "abort"}] * len(abort), finish_time=now)

    def step(self):
        from sglang.multi_model.vllm_backend.sampling import finish_reason_json

        step_start = time.time()
        outputs = self.engine.step()
        step_end = time.time()

        # Requests scheduled for the first time in this step (Prism: the new prefill batch).
        newly_scheduled, retracted = [], []
        for req in self.reqs.values():
            sreq = self._sched_req(req)
            if sreq is None:
                continue
            if req.out_queue_timestamp is None and sreq.num_computed_tokens > 0:
                req.out_queue_timestamp = step_start
                newly_scheduled.append(req.rid)
            if sreq.num_preemptions > req.num_preemptions:
                # vLLM preempted it for lack of KV (Prism: retract_decode).
                req.num_preemptions = sreq.num_preemptions
                retracted.append(req)
        if newly_scheduled:
            self.send_to_controller.send_pyobj(
                BatchRunReq(
                    rids=newly_scheduled, model=self.model_name, run_time=step_start, gpu_id=self.gpu_id
                )
            )
        if retracted:
            self.send_to_controller.send_pyobj(
                BatchRetractDecodeReq(
                    rids=[r.rid for r in retracted],
                    len_output_ids=[r.num_output_tokens for r in retracted],
                    model=self.model_name,
                    retract_time=step_end,
                )
            )

        is_stream_iter = self.decode_forward_ct % self.server_args.stream_interval == 0
        self.decode_forward_ct = (self.decode_forward_ct + 1) % (1 << 30)
        to_send, reasons = [], []
        for out in outputs:
            rid = out.request_id
            req = self.reqs.get(rid)
            if req is None:
                continue
            comp = out.outputs[0]
            new = len(comp.token_ids) - req.num_seen
            if new > 0:
                if req.out_queue_timestamp is None:
                    req.out_queue_timestamp = step_start
                if req.num_seen == 0:
                    req.num_cached_tokens = out.num_cached_tokens or 0
                    prefill = req.submitted_prompt_len - req.num_cached_tokens
                    self.prefill_token_count += prefill
                    self.token_count += prefill
                    if req.prefill_finish_timestamp is None:
                        req.prefill_finish_timestamp = step_end
                        decoded = new - 1
                    else:
                        decoded = new  # continuation after RECOMPUTE: its first token is a decode token
                else:
                    decoded = new
                self.decode_token_count += decoded
                self.token_count += decoded
                req.decode_timestamps.extend([step_end] * decoded)
                req.num_seen = len(comp.token_ids)
            req.text, req.token_ids = comp.text, list(comp.token_ids)
            reason = finish_reason_json(comp, req.num_output_tokens) if out.finished else None
            if out.finished:
                self._forget(req)
            if reason is not None or (req.obj.stream and (is_stream_iter or req.num_output_tokens == 1)):
                to_send.append(req)
                reasons.append(reason)
        if to_send:
            self._send_outputs(to_send, reasons, finish_time=step_end)

    def _send_outputs(self, reqs: List[_Req], reasons: List[Optional[dict]], finish_time=None):
        """Scheduler.stream_output + DetokenizerManager: full text so far and the benchmark's meta_info."""
        meta_info = []
        for req, reason in zip(reqs, reasons):
            meta_info.append(
                {
                    "prompt_tokens": req.prompt_len,
                    "completion_tokens": req.num_output_tokens,
                    "completion_tokens_wo_jump_forward": req.num_output_tokens,
                    "cached_tokens": req.num_cached_tokens,
                    "finish_reason": reason,
                    "arrival_timestamp": req.obj.arrival_time,
                    "out_queue_timestamp": req.out_queue_timestamp,
                    "prefill_finish_timestamp": req.prefill_finish_timestamp,
                    "finish_timestamp": finish_time if reason is not None else None,
                    "decode_timestamps": req.decode_timestamps,
                }
            )
        self.send_to_request_handler.send_pyobj(
            BatchStrOut(
                rids=[r.rid for r in reqs],
                output_strs=[r.prefix_text + r.text for r in reqs],
                meta_info=meta_info,
                finished_reason=reasons,
            )
        )

    def maybe_send_token_tput(self):
        now = time.time()
        elapsed = now - self.last_tput_update_time
        if elapsed < 1.0:
            return
        self.send_to_request_handler.send_pyobj(
            UpdateModelTput(
                model_name=self.model_name,
                instance_idx=self.instance_idx,
                latest_token_tput=self.token_count / elapsed,
                prefill_token_tput=self.prefill_token_count / elapsed,
                decode_token_tput=self.decode_token_count / elapsed,
                token_count=self.token_count,
                prefill_token_count=self.prefill_token_count,
                decode_token_count=self.decode_token_count,
            )
        )
        self.token_count = self.prefill_token_count = self.decode_token_count = 0
        self.last_tput_update_time = now

    # ------------------------------------------------------- control requests
    def process_control_requests(self, recv_reqs):
        activate, deactivate = [], []
        for r in recv_reqs:
            if isinstance(r, FlushCacheReq):
                self.flush_cache()
            elif isinstance(r, AbortReq):
                self.abort_request(r.rid)
            elif isinstance(r, UpdateWeightReqInput):
                self.send_to_request_handler.send_pyobj(
                    UpdateWeightReqOutput(False, "update_weights is not supported by the vLLM backend")
                )
            elif isinstance(r, ProfileReq):
                try:
                    if r == ProfileReq.START_PROFILE:
                        self.engine.start_profile()
                    else:
                        self.engine.stop_profile()
                except Exception as e:
                    logger.error(f"Profiling failed: {e}")
            elif isinstance(r, GetMemPoolSizeReq):
                self.send_to_request_handler.send_pyobj(
                    GetMemPoolSizeReqOutput(size=getattr(self, "max_total_num_tokens", 0), rid=r.rid)
                )
            elif isinstance(r, GetMemoryUsageReq):
                self.send_to_request_handler.send_pyobj(
                    GetMemoryUsageReqOutput(r.rid, self.get_memory_usage())
                )
            elif isinstance(r, ActivateReqInput):
                activate.append(r)
            elif isinstance(r, DeactivateReqInput):
                deactivate.append(r)
            elif isinstance(r, ResizeMemPoolReqInput):
                self.resize_mem_pool(r)
            else:
                logger.warning(f"Received invalid request: {r}")
        # Same ordering as Scheduler.process_activate_deactivate_requests.
        act = activate[0] if activate else None
        deact = deactivate[0] if deactivate else None
        if act and deact:
            if self.active:
                self.handle_deactivate_request(deact)
                self.handle_activate_request(act)
            else:
                self.handle_activate_request(act)
                self.handle_deactivate_request(deact)
        elif act:
            self.handle_activate_request(act)
        elif deact:
            self.handle_deactivate_request(deact)

    def flush_cache(self):
        if getattr(self, "engine", None) is None:
            return False
        if self.reqs:
            logger.warning("Cache not flushed because there are pending requests.")
            return False
        return self.engine.reset_prefix_cache()

    def abort_request(self, rid: str):
        req = self.reqs.get(rid)
        if req is not None:
            self.engine.abort_request([rid])
            self._forget(req)
        self.continuations = [r for r in self.continuations if r.rid != rid]

    def resize_mem_pool(self, r: ResizeMemPoolReqInput):
        if not self.enable_elastic_memory:
            logger.warning("Only elastic memory is supported for resize_mem_pool")
            return False
        self.kv_limit_bytes = (
            int(r.memory_pool_size * GB) if r.memory_pool_size is not None else self._initial_kv_limit_bytes()
        )
        if not self.active:
            return True  # applied on the next activation
        return self._set_kv_limit(self.kv_limit_bytes)

    def _reply(self, out):
        self.send_to_request_handler.send_pyobj(out)
        self.redis_client.send_pyobj(
            key=f"{self.server_args.engine_to_gpu_scheduler_key_prefix}:{self.gpu_id}", obj=out
        )

    def handle_activate_request(self, r: ActivateReqInput):
        gpu_id = self.gpu_id if r.gpu_id is None else r.gpu_id
        out = dict(rid=r.rid, gpu_id=gpu_id, model_name=r.model_name, instance_idx=r.instance_idx)
        if self.active or self.cuda_graphs:
            logger.warning("Engine is already activated (or runs with CUDA graphs)")
            self._reply(ActivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        if self.server_args.tp_size == 1 and gpu_id != self.gpu_id:
            # SingleModelRunner.activate can move a TP=1 model to another GPU; a vLLM engine is bound to
            # its device, so this backend cannot.
            logger.error(f"Cannot activate on GPU {gpu_id}: this vLLM engine runs on GPU {self.gpu_id}")
            self._reply(ActivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        tic = time.perf_counter()
        self._restore_gpu_memory(r.memory_pool_size)
        self.active = True
        for req in self.continuations:
            self._submit(req)
        self.continuations = []
        logger.info(f"Engine activated in {time.perf_counter() - tic:.4f}s")
        self._reply(ActivateReqOutput(success=True, memory_usage=self.get_memory_usage(), **out))

    def handle_deactivate_request(self, r: DeactivateReqInput):
        gpu_id = self.gpu_id if r.gpu_id is None else r.gpu_id
        out = dict(rid=r.rid, gpu_id=gpu_id, model_name=r.model_name, instance_idx=r.instance_idx)
        if not self.active or self.cuda_graphs:
            logger.warning("Engine is already deactivated (or runs with CUDA graphs)")
            self._reply(DeactivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        self.active = False
        tic = time.perf_counter()
        if r.evict_waiting_requests or (r.preempt and r.preempt_mode == PreemptMode.RECOMPUTE):
            self._evict_waiting_requests()
        if not r.preempt:
            self._run_to_completion()
        elif r.preempt_mode == PreemptMode.RETURN:
            self._complete_ongoing_requests()
        elif r.preempt_mode == PreemptMode.RECOMPUTE:
            self._retract_running_requests()
        else:
            raise NotImplementedError(f"Preempt mode {r.preempt_mode} is not supported")
        logger.info(
            f"Process ongoing requests with preempt ({r.preempt}) takes {time.perf_counter() - tic:.4f} s"
        )
        self._release_gpu_memory()
        logger.info(f"Total time taken for deactivation is {time.perf_counter() - tic:.2f} s")
        self._reply(DeactivateReqOutput(success=True, memory_usage=self.get_memory_usage(), **out))

    def _evict_waiting_requests(self):
        """Scheduler._evict_all_waiting_requests: unscheduled requests go back to the frontend queue."""
        waiting = [r for r in self.reqs.values() if r.out_queue_timestamp is None]
        waiting += self.continuations
        self.continuations = []
        if not waiting:
            return
        self.engine.abort_request([r.rid for r in waiting if r.rid in self.reqs])
        for r in waiting:
            self._forget(r)
            self.redis_client.send_pyobj(
                key=f"{self.server_args.frontend_generate_request_key_prefix}:{self.model_name}",
                obj=r.obj,
            )
        logger.info(f"Evicted {len(waiting)} requests back to Redis.")

    def _run_to_completion(self):
        logger.info(f"Number of requests to run to completion: {len(self.reqs)}")
        while self.engine.has_unfinished_requests():
            self.step()

    def _complete_ongoing_requests(self):
        """PreemptMode.RETURN: finish every request now with what it has generated (FINISH_LENGTH)."""
        reqs = list(self.reqs.values())
        logger.info(f"Number of requests to directly finish: {len(reqs)}")
        if not reqs:
            return
        self.engine.abort_request([r.rid for r in reqs])
        for r in reqs:
            self._forget(r)
        self._send_outputs(
            reqs,
            [{"type": "length", "length": r.num_output_tokens} for r in reqs],
            finish_time=time.time(),
        )

    def _retract_running_requests(self):
        """PreemptMode.RECOMPUTE: keep the requests with their output and recompute them on activation."""
        reqs = list(self.reqs.values())
        if reqs:
            self.engine.abort_request([r.rid for r in reqs])
        for r in reqs:
            self._forget(r)
            r.prefix_token_ids = r.prefix_token_ids + r.token_ids
            r.prefix_text = r.prefix_text + r.text
            r.token_ids, r.text = [], ""
            self.continuations.append(r)
        logger.info(
            f"Retract running requests: {len(reqs)} "
            f"(rid, tokens, chars kept): {[(r.rid, len(r.prefix_token_ids), len(r.prefix_text)) for r in reqs]}"
        )
        self.send_to_controller.send_pyobj(
            BatchRetractDecodeReq(
                rids=[r.rid for r in reqs],
                len_output_ids=[r.num_output_tokens for r in reqs],
                model=self.model_name,
                retract_time=time.time(),
            )
        )

    def cleanup(self):
        if self.shm is not None:
            try:
                self.shm.close()
                self.shm.unlink()
            except Exception:
                pass
            self.shm = None


def _setup_env(server_args: ServerArgs, gpu_ids: List[int]):
    """Must run before vLLM (and CUDA) is initialized in this process."""
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible:
        visible = visible.split(",")
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(visible[i] for i in gpu_ids)
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in gpu_ids)
    # The same devices as nvidia-smi ids (indices or UUIDs), for _gpu_free_total.
    os.environ["PRISM_PHYSICAL_GPUS"] = os.environ["CUDA_VISIBLE_DEVICES"]
    # In-process EngineCore: the adapter drives it with step(), like Prism's scheduler loop.
    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    os.environ.setdefault("VLLM_NO_USAGE_STATS", "1")
    if len(gpu_ids) > 1:
        # Several TP engines share these GPUs: the symmetric-memory all-reduce's multicast setup
        # intermittently hung the second engine's start-up (CUDA "unknown error" in
        # init_multicast_for_block); vLLM then uses its custom all-reduce / NCCL.
        os.environ.setdefault("VLLM_ALLREDUCE_USE_SYMM_MEM", "0")
    if server_args.enable_worker_pool:
        # A slot builds an engine per activation: use the construction shortcuts of vllm_patches.
        for flag in ("PRISM_VLLM_SKIP_PROFILE", "PRISM_VLLM_CACHE_RENDERER", "PRISM_VLLM_SKIP_WARMUP"):
            os.environ.setdefault(flag, "1")
    # The kvcached variables (kvcached_env) are set by the parent before this process starts: kvcached's
    # autopatch .pth imports kvcached at interpreter start-up, which fixes its IPC name then.


def kvcached_env(server_args: ServerArgs, gpu_ids: List[int]) -> Dict[str, str]:
    """Environment for an engine process. The KV usage segment is named like the SGLang engine's
    (ipc_{gpu}_{model}_{user}, or ipc_{gpu}_{worker}_{user} for a worker-pool slot) so the GPU
    scheduler's ResourceManager finds it."""
    if not server_args.enable_elastic_memory:
        return {"ENABLE_KVCACHED": "false"}
    owner = server_args.worker_id if server_args.enable_worker_pool else server_args.model_name
    return {
        "ENABLE_KVCACHED": "true",
        "KVCACHED_AUTOPATCH": "1",
        "KVCACHED_IPC_NAME": f"ipc_{gpu_ids[0]}_{owner}_{getpass.getuser()}",
    }


def run_vllm_engine_process(
    server_args: ServerArgs,
    port_args: PortArgs,
    gpu_ids: List[int],
    pipe_writer,
):
    configure_logger(server_args, prefix=f" {server_args.model_name} GPU={gpu_ids} vLLM")
    adapter = None
    try:
        _setup_env(server_args, gpu_ids)
        adapter = VllmEngineAdapter(server_args, port_args, gpu_ids)
        signal.signal(signal.SIGTERM, lambda *_: (adapter.cleanup(), os._exit(0)))
        pipe_writer.send(adapter.get_memory_usage())
        adapter.event_loop()
    except Exception:
        logger.error(get_exception_traceback())
        if adapter is not None:
            adapter.cleanup()
        try:
            pipe_writer.send(get_exception_traceback())
        except Exception:
            pass
        raise


class VllmWorkerSlot(VllmEngineAdapter):
    """A worker-pool slot (--enable-worker-pool): one process per (GPU, worker id) that serves whichever
    model the GPU scheduler assigns to it, like WorkerPoolModelRunner in the SGLang backend.

    A vLLM engine is bound to one model, so activation builds an engine for the requested model in this
    process and deactivation tears it down (vllm_patches.teardown_engine keeps the CUDA context and the
    process group). Weights come from the shared CPU cache (weight_cache.py, load format `prism_shm`) and
    are read from the checkpoint only for a model that has no cache yet, which is then saved.
    """

    def __init__(self, server_args: ServerArgs, port_args: PortArgs, gpu_ids: List[int],
                 model_names_to_model_paths: Dict[str, str]):
        from sglang.multi_model.vllm_backend import vllm_patches

        vllm_patches.apply()
        self.server_args = server_args
        self.port_args = port_args
        self.gpu_ids = gpu_ids
        self.gpu_id = gpu_ids[0]
        self.tp = len(gpu_ids)  # a TP slot spans tp GPUs and serves models with that tp_size
        self.worker_id = server_args.worker_id
        self.model_paths = model_names_to_model_paths
        self.model_tp = getattr(server_args, "prism_model_tp", {}) or {}
        self.model_name = None
        self.instance_idx = getattr(server_args, "instance_idx", 0)
        self.enable_elastic_memory = server_args.enable_elastic_memory
        self.ipc_name = f"ipc_{self.gpu_id}_{self.worker_id}_{getpass.getuser()}"
        self.cuda_graphs = False
        self.engine = None
        self.weights_bytes = 0
        self._init_ipc()
        self._init_state()
        self.active = False
        if os.environ.get("PRISM_VLLM_WARM_SLOT", "1") == "1":
            self._warm_up_slot()

    def _warm_up_slot(self):
        """Build and tear down one engine at start-up. The first engine of a process pays for CUDA and
        process-group initialization and kernel JIT (~7 s measured); later ones take ~0.5 s. Prism's
        WorkerPoolModelRunner likewise initializes its runtime before the first activation."""
        from sglang.multi_model.vllm_backend import vllm_patches, weight_cache

        cached = [m for m, p in self.model_paths.items()
                  if self.model_tp.get(m, 1) == self.tp and weight_cache.exists(p, 0, self.tp)]
        if not cached:
            return
        smallest = min(cached, key=lambda m: weight_cache.meta_nbytes(self.model_paths[m], 0, self.tp))
        tic = time.perf_counter()
        self._build_engine(smallest)
        engine, self.engine, self.vllm_scheduler = self.engine, None, None
        vllm_patches.teardown_engine(engine)
        del engine
        self.weights_bytes, self.model_name = 0, None
        self._warmed = True
        logger.info(f"Slot warmed up with {smallest} in {time.perf_counter() - tic:.1f}s")

    def _init_ipc(self):
        super()._init_ipc()
        # Activate/deactivate requests come from this GPU's scheduler (WorkerPool in gpu/worker_pool.py).
        self.recv_from_gpu_scheduler = zmq.Context.instance().socket(zmq.PULL)
        self.recv_from_gpu_scheduler.bind(f"ipc://gpu_scheduler_{self.gpu_id}_to_worker_{self.worker_id}")

    def recv_control_requests(self):
        reqs = super().recv_control_requests()
        while True:
            try:
                reqs.append(self.recv_from_gpu_scheduler.recv_pyobj(zmq.NOBLOCK))
            except zmq.ZMQError:
                return reqs

    def _build_engine(self, model_name: str):
        from vllm import LLMEngine

        from sglang.multi_model.vllm_backend import vllm_patches, weight_cache

        path = self.model_paths[model_name]
        self.model_name = model_name
        self.server_args.model_name = model_name
        self.server_args.model_path = path
        self.server_args.tokenizer_path = path
        cached = weight_cache.exists(path, 0, self.tp)
        self.server_args.tp_size = self.tp
        args = self._engine_args()
        if cached:
            args.load_format = "prism_shm"
            args.model_loader_extra_config = {"cache_key": path}
        if self.tp > 1:
            # Keep the TP worker processes (CUDA contexts, process group) between engines.
            args.distributed_executor_backend = vllm_patches.persistent_executor_class()
        # Only the slot's first engine profiles GPU memory (later ones reuse the result), so only the
        # warm-up needs to exclude the other slots on the GPU.
        locks = self._gpu_locks() if not getattr(self, "_warmed", False) else []
        try:
            tic = time.perf_counter()
            with vllm_patches.fast_build():
                self.engine = LLMEngine.from_engine_args(args)
            logger.info(
                f"vLLM engine for {model_name} created in {time.perf_counter() - tic:.3f}s "
                f"(weights from {'shared cache' if cached else 'checkpoint'})"
            )
        finally:
            for f in locks:
                f.close()
        if not cached:
            self.engine.collective_rpc("prism_save_weight_cache", args=(path,))
        self.weights_bytes = weight_cache.meta_nbytes(path, 0, self.tp)  # per rank
        self._bind_engine()

    def handle_activate_request(self, r: ActivateReqInput):
        gpu_id = self.gpu_id if r.gpu_id is None else r.gpu_id
        out = dict(rid=r.rid, gpu_id=gpu_id, model_name=r.model_name, instance_idx=r.instance_idx)
        if self.active:
            logger.warning(f"Worker already serves {self.model_name}")
            self._reply(ActivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        if self.model_tp.get(r.model_name, 1) != self.tp:
            logger.error(f"{r.model_name} needs tp={self.model_tp.get(r.model_name, 1)}; this slot has tp={self.tp}")
            self._reply(ActivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        tic = time.perf_counter()
        try:
            self._build_engine(r.model_name)
        except Exception:
            logger.error(f"Activation of {r.model_name} failed:\n{get_exception_traceback()}")
            self.engine = None
            self._reply(ActivateReqOutput(success=False, memory_usage=self.get_memory_usage(), **out))
            return
        change_logger_format(prefix=f" GPU={self.gpu_id} Worker {self.worker_id} ({r.model_name}) vLLM")
        pool_gb = r.memory_pool_size
        if pool_gb is None:
            pool_gb = getattr(self.server_args, "prism_pool_sizes", {}).get(r.model_name)
        self.kv_limit_bytes = int(pool_gb * GB) if pool_gb is not None else self._initial_kv_limit_bytes()
        if self.enable_elastic_memory:
            self._set_kv_limit(self.kv_limit_bytes)
        self.active = True
        logger.info(f"Activate model {r.model_name} time cost: {time.perf_counter() - tic:.4f}s.")
        self._reply(ActivateReqOutput(success=True, memory_usage=self.get_memory_usage(), **out))

    def _release_gpu_memory(self):
        from sglang.multi_model.vllm_backend import vllm_patches

        engine, self.engine, self.vllm_scheduler = self.engine, None, None
        vllm_patches.teardown_engine(engine)
        self.weights_bytes = 0
        self.model_name = None

    def _retract_running_requests(self):
        """RECOMPUTE in a slot: the model may next run on another slot or GPU, so the requests go back to
        the model's frontend queue carrying their progress (CONTINUATION_ATTR) and are continued by
        whichever slot serves the model next."""
        reqs = list(self.reqs.values())
        if reqs:
            self.engine.abort_request([r.rid for r in reqs])
        for r in reqs:
            self._forget(r)
            r.prefix_token_ids = r.prefix_token_ids + r.token_ids
            r.prefix_text = r.prefix_text + r.text
            r.prompt_ids = list(self._prompt_ids(r))
            setattr(r.obj, CONTINUATION_ATTR, {k: getattr(r, k) for k in CONTINUATION_FIELDS})
            self.redis_client.send_pyobj(
                key=f"{self.server_args.frontend_generate_request_key_prefix}:{self.model_name}",
                obj=r.obj,
            )
        logger.info(f"Retract running requests to the frontend queue: {len(reqs)}")
        self.send_to_controller.send_pyobj(
            BatchRetractDecodeReq(
                rids=[r.rid for r in reqs],
                len_output_ids=[r.num_output_tokens for r in reqs],
                model=self.model_name,
                retract_time=time.time(),
            )
        )


def run_vllm_worker_process(
    server_args: ServerArgs,
    port_args: PortArgs,
    gpu_ids: List[int],
    pipe_writer,
    model_names_to_model_paths: Dict[str, str],
):
    configure_logger(server_args, prefix=f" GPU={gpu_ids[0]} Worker={server_args.worker_id} vLLM")
    slot = None
    try:
        _setup_env(server_args, gpu_ids)
        slot = VllmWorkerSlot(server_args, port_args, gpu_ids, model_names_to_model_paths)
        signal.signal(signal.SIGTERM, lambda *_: (slot.cleanup(), os._exit(0)))
        pipe_writer.send(slot.get_memory_usage())
        slot.event_loop()
    except Exception:
        logger.error(get_exception_traceback())
        try:
            pipe_writer.send(get_exception_traceback())
        except Exception:
            pass
        raise


def run_weight_cache_prewarm(server_args: ServerArgs, gpu_ids: List[int], models: List, pipe_writer):
    """Fill the shared CPU weight cache for the given (model path, tp_size) pairs (the vLLM backend's
    counterpart of --enable-cpu-share-memory, which loads every model to shared CPU memory at start-up).
    A TP model is cached per rank (its shards), built on GPUs 0..tp-1."""
    configure_logger(server_args, prefix=" WeightCache")
    try:
        os.environ["ENABLE_KVCACHED"] = "false"
        _setup_env(server_args, gpu_ids)
        from vllm import EngineArgs, LLMEngine

        from sglang.multi_model.vllm_backend import vllm_patches, weight_cache

        vllm_patches.apply()
        for path, tp in models:
            if weight_cache.exists(path, 0, tp):
                continue
            tic = time.perf_counter()
            engine = LLMEngine.from_engine_args(EngineArgs(
                model=path, load_format=server_args.load_format, enforce_eager=True,
                enable_prefix_caching=False, max_model_len=-1, async_scheduling=False,
                disable_log_stats=True, trust_remote_code=server_args.trust_remote_code,
                dtype=server_args.dtype, kv_cache_memory_bytes=1 << 30, gpu_memory_utilization=0.5,
                tensor_parallel_size=tp, worker_extension_cls=WORKER_EXTENSION,
            ))
            engine.collective_rpc("prism_save_weight_cache", args=(path,))
            vllm_patches.teardown_engine(engine)
            del engine
            logger.info(f"Cached {path} in {time.perf_counter() - tic:.1f}s")
        pipe_writer.send("ok")
    except Exception:
        logger.error(get_exception_traceback())
        pipe_writer.send(get_exception_traceback())
