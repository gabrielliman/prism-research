"""Tensor-parallel executor of the vLLM worker pool: a MultiprocExecutor whose worker processes outlive
the engine, so a slot rebuilds a TP engine without re-spawning the ranks or re-creating their process
group (see 4. in vllm_patches' docstring). Import through vllm_patches.persistent_executor_class().
"""
import logging
import time

from vllm.v1.executor.multiproc_executor import MultiprocExecutor

from sglang.multi_model.vllm_backend.vllm_patches import (
    _live_executor,
    _prism_reinit_worker,
    _prism_release_worker,
)

logger = logging.getLogger(__name__)


class PrismPersistentMultiprocExecutor(MultiprocExecutor):
    def __new__(cls, vllm_config, *args, **kwargs):
        live = _live_executor[0]
        if (live is not None and not live.is_failed
                and live.world_size == vllm_config.parallel_config.world_size):
            return live
        return super().__new__(cls)

    def __init__(self, vllm_config, monitor_workers: bool = True):
        if getattr(self, "_prism_released", False):
            # Reuse the workers for the next engine: adopt its config, re-create each rank's Worker.
            tic = time.perf_counter()
            self.vllm_config = vllm_config
            self.model_config = vllm_config.model_config
            self.cache_config = vllm_config.cache_config
            self.lora_config = vllm_config.lora_config
            self.load_config = vllm_config.load_config
            self.parallel_config = vllm_config.parallel_config
            self.scheduler_config = vllm_config.scheduler_config
            self.device_config = vllm_config.device_config
            self.speculative_config = vllm_config.speculative_config
            self.observability_config = vllm_config.observability_config
            self.failure_callback = None
            self.collective_rpc(_prism_reinit_worker, args=(vllm_config,))
            self._prism_released = False
            logger.info(f"Prism: reused {self.world_size} TP workers in {time.perf_counter() - tic:.3f}s")
            return
        super().__init__(vllm_config, monitor_workers)
        self._prism_released = False
        _live_executor[0] = self

    def prism_release(self):
        """Free every rank's model and KV cache; the workers stay for the next engine."""
        self.collective_rpc(_prism_release_worker)
        self._prism_released = True

    def shutdown(self):
        if self is _live_executor[0] and self._prism_released:
            return  # kept for the next engine; final shutdown at process exit
        super().shutdown()

