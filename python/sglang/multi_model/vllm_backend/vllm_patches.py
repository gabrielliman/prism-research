"""Changes to vLLM needed by Prism's worker pool, applied at runtime and kept in this repository.

A worker-pool slot is a long-lived process that serves different models over time. vLLM binds an engine
to one model, so the slot builds a new engine per activation and tears it down on deactivation. These
patches make that cheap and safe; they target vLLM 0.30.0 (the version in docker/prism-vllm) and are
checked against it at import:

1. `prism_shm` load format: builds the model from the shared CPU weight cache (weight_cache.py) instead of
   the checkpoint. The cached tensors are already processed (process_weights_after_loading ran when they
   were captured), so it is skipped.
2. `teardown_engine`: EngineCore.shutdown() ends with cleanup_dist_env_and_memory(), which destroys the
   process group; the next engine in the process would re-create it. The slot instead shuts the executor
   and scheduler down and keeps the distributed state, which vLLM's init_distributed_environment /
   ensure_model_parallel_initialized reuse when they find it initialized. kvcached is shut down explicitly
   (its own patch hooks EngineCore.shutdown, which is not called).
3. Faster engine construction, measured with polyaxon/experiments/engine_swap.py (opt-in, enabled by the
   worker-pool slots):
   * PRISM_VLLM_SKIP_PROFILE=1: with an explicit KV size (kv_cache_memory_bytes) vLLM still runs a
     profiling forward pass before allocating the KV cache; it is skipped. Without an explicit size
     (kvcached), the result of the first profiling of a model is reused for the next engines of the
     same model and configuration.
   * PRISM_VLLM_CACHE_RENDERER=1: the renderer (tokenizer + a deep-copied tokenizer pool, ~1.5 s) is
     built once per model and rebound to each new engine's config.
   * `fast_build()`: vLLM calls gc.collect() ~10 times while building an engine (memory accounting); with
     the whole vLLM/torch heap that is ~1.5-2 s. They are skipped during construction; teardown_engine
     still runs a full collection, which is what releases the previous engine.
   * PRISM_VLLM_SKIP_WARMUP=1: skips the kernel warmup (FlashInfer autotune, dummy runs) of every engine
     after the first in the process; the kernels are already loaded.
4. `persistent_executor_class()` (tensor parallelism): with TP > 1 vLLM runs each rank in a worker process
   that MultiprocExecutor spawns per engine (CUDA + NCCL initialization every time). The returned executor
   class keeps the worker processes, their CUDA contexts and process group between engines (the paper's
   "pre-warmed engine pool with reusable distributed contexts"): a new engine re-creates only each rank's
   Worker (model, KV cache) inside the existing processes, and teardown releases only those.
"""

import contextlib
import gc
import logging
import os
import time

import torch

logger = logging.getLogger(__name__)

SUPPORTED_VLLM = "0.30.0"
_applied = False


def apply():
    global _applied
    if _applied:
        return
    import vllm

    if vllm.__version__ != SUPPORTED_VLLM:
        logger.warning(
            f"Prism vLLM patches target vLLM {SUPPORTED_VLLM}, found {vllm.__version__}; "
            "re-run polyaxon/test_switching.py and the worker-pool tests before relying on them."
        )
    _register_shm_loader()
    _patch_profile_run()
    _patch_renderer_cache()
    _patch_warmup()
    _applied = True


def _on(name: str) -> bool:
    return os.environ.get(name) == "1"


def _register_shm_loader():
    from vllm.distributed import get_tensor_model_parallel_rank, get_tensor_model_parallel_world_size
    from vllm.model_executor.model_loader import register_model_loader
    from vllm.model_executor.model_loader.base_loader import BaseModelLoader
    from vllm.utils.torch_utils import set_default_torch_dtype

    from sglang.multi_model.vllm_backend import weight_cache

    @register_model_loader("prism_shm")
    class PrismShmModelLoader(BaseModelLoader):
        def download_model(self, model_config) -> None:
            pass

        def load_weights(self, model, model_config) -> None:
            # The cache is keyed by the model path Prism knows (e.g. the HF repo id); vLLM may have
            # replaced model_config.model with a local snapshot path, so the key is passed explicitly.
            key = (self.load_config.model_loader_extra_config or {}).get("cache_key", model_config.model)
            cache = weight_cache.open_cache(
                key, get_tensor_model_parallel_rank(), get_tensor_model_parallel_world_size()
            )
            if cache is None:
                raise FileNotFoundError(f"No Prism weight cache for {key}")
            tic = time.perf_counter()
            n = cache.copy_into(model)
            logger.info(
                f"Prism: loaded {n / (1 << 30):.2f} GB of weights from the shared cache in "
                f"{time.perf_counter() - tic:.3f}s"
            )

        def load_model(self, vllm_config, model_config, prefix: str = ""):
            device = torch.device(vllm_config.load_config.device or vllm_config.device_config.device)
            with set_default_torch_dtype(model_config.dtype):
                with device:
                    model = self.create_model(vllm_config, model_config, prefix)
                self.load_weights(model, model_config)
            return model.eval()


def _patch_profile_run():
    from vllm.v1.worker import gpu_worker

    Worker = gpu_worker.Worker
    original = Worker.determine_available_memory
    if getattr(original, "_prism_patched", False):
        return

    cache = {}
    side_effects = ("available_kv_cache_memory_bytes", "non_torch_memory", "total_consumed",
                    "peak_activation_memory", "cudagraph_memory_estimate")

    def determine_available_memory(self, *args, **kwargs):
        kv_bytes = self.cache_config.kv_cache_memory_bytes
        if not _on("PRISM_VLLM_SKIP_PROFILE"):
            return original(self, *args, **kwargs)
        if kv_bytes:
            return int(kv_bytes)
        mc, sc = self.model_config, self.vllm_config.scheduler_config
        key = (mc.model, mc.max_model_len, str(mc.dtype), sc.max_num_batched_tokens, sc.max_num_seqs,
               self.cache_config.gpu_memory_utilization, os.environ.get("ENABLE_KVCACHED"))
        if key not in cache:
            value = original(self, *args, **kwargs)
            cache[key] = (value, {a: getattr(self, a) for a in side_effects if hasattr(self, a)})
        value, attrs = cache[key]
        for a, v in attrs.items():
            setattr(self, a, v)
        return value

    determine_available_memory._prism_patched = True
    Worker.determine_available_memory = determine_available_memory


def _patch_renderer_cache():
    import vllm.v1.engine.llm_engine as llm_engine

    original = llm_engine.renderer_from_config
    if getattr(original, "_prism_patched", False):
        return
    cache = {}

    def renderer_from_config(config, **kwargs):
        mc = config.model_config
        if not _on("PRISM_VLLM_CACHE_RENDERER") or kwargs or mc.is_multimodal_model:
            return original(config, **kwargs)
        key = (mc.tokenizer, mc.tokenizer_mode, mc.tokenizer_revision, mc.trust_remote_code,
               mc.skip_tokenizer_init, mc.renderer_num_workers)
        renderer = cache.get(key)
        if renderer is None:
            renderer = cache[key] = original(config)
        # Rebind to this engine's config (max_model_len etc. may differ between engines).
        renderer.config = config
        renderer.model_config = config.model_config
        return renderer

    renderer_from_config._prism_patched = True
    llm_engine.renderer_from_config = renderer_from_config


def _patch_warmup():
    from vllm.v1.worker import gpu_worker

    Worker = gpu_worker.Worker
    original = Worker.compile_or_warm_up_model
    if getattr(original, "_prism_patched", False):
        return
    done = set()

    def compile_or_warm_up_model(self, *args, **kwargs):
        key = (self.model_config.model, self.model_config.enforce_eager)
        if _on("PRISM_VLLM_SKIP_WARMUP") and self.model_config.enforce_eager and key in done:
            from vllm.v1.worker.worker_base import CompilationTimes

            return CompilationTimes(language_model=0.0, encoder=0.0)
        result = original(self, *args, **kwargs)
        done.add(key)
        return result

    compile_or_warm_up_model._prism_patched = True
    Worker.compile_or_warm_up_model = compile_or_warm_up_model


@contextlib.contextmanager
def fast_build():
    """Skip vLLM's full gc.collect() calls while an engine is being built."""
    collect = gc.collect
    gc.collect = lambda *args, **kwargs: 0
    try:
        yield
    finally:
        gc.collect = collect


# --------------------------------------------------------------------- tensor parallelism

def _prism_release_worker(wrapper) -> int:
    """Runs in a TP worker process: free this rank's model and KV cache, keep the process and its
    process group. Returns the bytes still allocated by torch."""
    worker = wrapper.worker
    if worker is not None:
        wrapper._prism_rank_info = dict(
            local_rank=worker.local_rank, rank=worker.rank,
            distributed_init_method=worker.distributed_init_method,
            is_driver_worker=worker.is_driver_worker,
        )
        runner = getattr(worker, "model_runner", None)
        if runner is not None:
            with fast_build():  # ModelRunner.shutdown() runs its own full gc.collect()
                runner.shutdown()
            worker.model_runner = None
        wrapper.worker = None
    if os.environ.get("ENABLE_KVCACHED", "false").lower() in ("true", "1"):
        from kvcached.integration.vllm.interfaces import shutdown_kvcached

        shutdown_kvcached()
    gc.collect()
    torch.cuda.empty_cache()
    return torch.cuda.memory_allocated()


def _prism_reinit_worker(wrapper, vllm_config) -> None:
    """Runs in a TP worker process: create this rank's Worker for a new model in the existing process
    (WorkerProc.__init__ without spawning; init_device finds the process group initialized)."""
    from vllm.platforms import current_platform

    info = wrapper._prism_rank_info
    all_kwargs = [{} for _ in range(vllm_config.parallel_config.world_size)]
    all_kwargs[wrapper.rpc_rank] = dict(vllm_config=vllm_config, shared_worker_lock=None, **info)
    with fast_build():
        wrapper.init_worker(all_kwargs)
        wrapper.init_device()
        wrapper.load_model()
    current_platform.update_block_size_for_backend(vllm_config)


_live_executor = [None]


def persistent_executor_class():
    """MultiprocExecutor whose worker processes outlive the engine (see 4. in the module docstring).
    Defined in its own module: vLLM pickles the executor class into the config sent to the workers."""
    from sglang.multi_model.vllm_backend.persistent_executor import PrismPersistentMultiprocExecutor

    return PrismPersistentMultiprocExecutor


def teardown_engine(engine) -> None:
    """Release an in-process LLMEngine's GPU memory while keeping the process group for the next one."""
    tic = time.perf_counter()
    steps = {}

    def mark(name):
        nonlocal tic
        now = time.perf_counter()
        steps[name] = round(now - tic, 3)
        tic = now

    total_tic = tic
    core = engine.engine_core.engine_core
    try:
        core.structured_output_manager.clear_backend()
    except Exception as e:
        logger.warning(f"structured output teardown: {e}")
    mark("structured_output")
    release = getattr(core.model_executor, "prism_release", None)
    if release is not None:
        release()  # persistent TP workers: free their model and KV cache, keep the processes
    else:
        # ModelRunner.shutdown() runs a full gc.collect() (~0.5 s); one collection below is enough.
        with fast_build():
            core.model_executor.shutdown()
    mark("executor")
    core.scheduler.shutdown()
    mark("scheduler")
    if os.environ.get("ENABLE_KVCACHED", "false").lower() in ("true", "1"):
        from kvcached.integration.vllm.interfaces import shutdown_kvcached

        if not shutdown_kvcached():
            logger.warning("kvcached shutdown deferred")
    mark("kvcached")
    finalizer = getattr(engine, "_finalizer", None)
    if finalizer is not None:
        finalizer()
    mark("finalizer")
    # Drop the references that keep the model and KV tensors alive.
    executor = core.model_executor
    worker = getattr(getattr(executor, "driver_worker", None), "worker", None)
    if worker is not None:
        worker.model_runner = None
    core.model_executor = None
    core.scheduler = None
    engine.engine_core = None
    gc.unfreeze()
    gc.collect()
    mark("gc")
    torch.cuda.empty_cache()
    mark("empty_cache")
    logger.info(
        f"Prism: engine torn down in {time.perf_counter() - total_tic:.3f}s {steps}, "
        f"{torch.cuda.memory_allocated() / (1 << 30):.2f} GB still allocated"
    )
