"""vLLM worker extension that gives a vLLM worker Prism's activate/deactivate primitives.

Loaded into every vLLM worker with `worker_extension_cls` and called through `collective_rpc`, so it also
works for tensor parallelism (each rank offloads its own shard).

Weights: mirrors SingleModelRunner (sglang/srt/model_executor/single_model_runner.py), which keeps a pinned
CPU copy of the weights (`state_dict_host`) and copies it to the GPU on activation. Here the pinned copy is
taken from the live GPU model on the first offload and the parameters are re-pointed (`tensor.data = ...`)
instead of rebuilding the module, because a vLLM engine cannot swap its model object. The new GPU addresses
invalidate captured CUDA graphs, so the adapter always runs vLLM with enforce_eager (Prism's examples use
--disable-cuda-graph too).

KV cache: with kvcached (elastic memory) the KV pages are owned by kvcached and released by lowering the
instance limit (`prism_set_kv_limit`). Without kvcached the KV cache is a fixed allocation; it is released by
shrinking its storage to 0 bytes and restored at the same size, like ReqToTokenPool.release() in Prism.
"""

import logging
import time
from typing import Dict, List, Tuple

import torch

logger = logging.getLogger(__name__)


class PrismWorkerExtension:
    def _prism_model(self) -> torch.nn.Module:
        runner = self.model_runner
        return runner.get_model() if hasattr(runner, "get_model") else runner.model

    def _prism_device_tensors(self) -> List[Tuple[str, torch.Tensor]]:
        model = self._prism_model()
        tensors = list(model.named_parameters()) + list(model.named_buffers())
        return [(name, t) for name, t in tensors if t.device.type == "cuda"]

    def prism_snapshot_weights(self) -> int:
        """Take the pinned CPU copy of the weights now (Prism pins its CPU weights when it loads the model),
        so that deactivations only free GPU memory. Returns the bytes copied."""
        tic = time.perf_counter()
        if getattr(self, "_prism_host", None) is None:
            # Weights do not change while serving, so the pinned copy is taken once and reused.
            # Tensors that share storage (e.g. tied embeddings) share one host copy.
            self._prism_host: Dict[str, torch.Tensor] = {}
            self._prism_alias: Dict[str, str] = {}
            self._prism_device = None
            by_ptr: Dict[int, str] = {}
            for name, t in self._prism_device_tensors():
                self._prism_device = t.device
                ptr = t.data_ptr()
                if ptr in by_ptr and self._prism_host[by_ptr[ptr]].shape == t.shape:
                    self._prism_alias[name] = by_ptr[ptr]
                    continue
                host = torch.empty(t.shape, dtype=t.dtype, device="cpu", pin_memory=True)
                host.copy_(t.data)
                self._prism_host[name] = host
                by_ptr[ptr] = name
            self._prism_weight_bytes = sum(
                h.numel() * h.element_size() for h in self._prism_host.values()
            )
            logger.info(
                f"Prism: pinned CPU copy of {self._prism_weight_bytes / (1 << 30):.2f} GB of weights "
                f"in {time.perf_counter() - tic:.2f}s"
            )
        return self._prism_weight_bytes

    def prism_offload_weights(self) -> int:
        """Move the weights to pinned CPU memory and free their GPU memory. Returns bytes freed."""
        tic = time.perf_counter()
        before = torch.cuda.memory_allocated()
        self.prism_snapshot_weights()
        for name, t in self._prism_device_tensors():
            t.data = torch.empty(0, dtype=t.dtype, device=t.device)
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        freed = before - torch.cuda.memory_allocated()
        logger.info(
            f"Prism: offloaded weights to CPU in {time.perf_counter() - tic:.4f}s, "
            f"freed {freed / (1 << 30):.2f} GB"
        )
        return freed

    def prism_load_weights(self) -> int:
        """Copy the pinned CPU weights back to the GPU. Returns bytes allocated."""
        tic = time.perf_counter()
        before = torch.cuda.memory_allocated()
        model = self._prism_model()
        named = dict(model.named_parameters())
        named.update(dict(model.named_buffers()))
        loaded: Dict[str, torch.Tensor] = {}
        for name, host in self._prism_host.items():
            loaded[name] = host.to(self._prism_device, non_blocking=True)
            named[name].data = loaded[name]
        for name, target in self._prism_alias.items():
            named[name].data = loaded[target]
        torch.cuda.synchronize()
        allocated = torch.cuda.memory_allocated() - before
        logger.info(
            f"Prism: loaded weights to GPU in {time.perf_counter() - tic:.4f}s, "
            f"{allocated / (1 << 30):.2f} GB"
        )
        return allocated

    def _prism_kv_storages(self):
        storages = {}
        stack = list(self.model_runner.kv_caches)
        while stack:
            t = stack.pop()
            if isinstance(t, (list, tuple)):
                stack.extend(t)
            elif isinstance(t, torch.Tensor):
                s = t.untyped_storage()
                storages[s.data_ptr()] = s
        return list(storages.values())

    def prism_release_kv(self) -> int:
        """Free a static (non-kvcached) KV cache. Its contents are lost: reset the prefix cache first."""
        if getattr(self, "_prism_kv", None) is not None:
            return 0
        self._prism_kv = [(s, s.nbytes()) for s in self._prism_kv_storages()]
        freed = sum(n for _, n in self._prism_kv)
        for s, _ in self._prism_kv:
            s.resize_(0)
        torch.cuda.empty_cache()
        return freed

    def prism_restore_kv(self) -> int:
        """Re-allocate a KV cache released by prism_release_kv, with the same size."""
        if getattr(self, "_prism_kv", None) is None:
            return 0
        total = 0
        for s, nbytes in self._prism_kv:
            s.resize_(nbytes)
            total += nbytes
        self._prism_kv = None
        return total

    def prism_kv_bytes(self) -> int:
        """Bytes allocated for a static KV cache (0 while released)."""
        if getattr(self, "_prism_kv", None) is not None:
            return 0
        return sum(s.nbytes() for s in self._prism_kv_storages())

    def prism_set_kv_limit(self, limit_bytes: int, revision: int) -> dict:
        """Set this instance's kvcached physical KV limit (kvcached's process-local control API)."""
        from kvcached.control import set_instance_memory_limit

        return set_instance_memory_limit(int(limit_bytes), revision=int(revision))

    def _prism_kv_pools(self):
        from kvcached.pool_registry import get_registered_kv_cache_pools

        return [manager for manager, _ in get_registered_kv_cache_pools()]

    def prism_min_kv_limit(self) -> int:
        """Smallest kvcached limit a shrink can reach: one page per layer and pool. A limit of 0 never
        completes because vLLM's block pool always keeps its null block allocated."""
        return sum(m.page_size * m.num_layers * m.num_kv_buffers for m in self._prism_kv_pools())

    def prism_trim_kv(self) -> None:
        """Unmap kvcached's pre-allocated (reserved) pages."""
        for m in self._prism_kv_pools():
            m.trim()

    def prism_kv_mapped_bytes(self) -> int:
        """Physical KV memory currently mapped by kvcached (in-use + reserved pages)."""
        return sum(int(m.memory_limit_state()["mapped_bytes"]) for m in self._prism_kv_pools())
