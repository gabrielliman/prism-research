"""Shared CPU weight cache for the vLLM worker pool.

Plays the role of Prism's `--enable-cpu-share-memory` / model service for the vLLM backend: the processed
weights of each model are kept once in host shared memory (/dev/shm) and any worker slot, on any GPU, can
build a vLLM engine for that model by copying them to its GPU instead of reading the checkpoint.

Layout, one directory per model under PRISM_WEIGHT_CACHE_DIR (default /dev/shm/prism_weights_<user>):
  data.bin   all tensors back to back (256-byte aligned)
  meta.json  [{name, dtype, shape, offset}], aliases {name: name}; written last, marks the cache complete

The tensors are the model's parameters and buffers *after* vLLM's process_weights_after_loading, i.e. what
the model holds on the GPU while serving. They are captured from a loaded model (`save`) and mapped
read-only by other processes (`open_cache`), which register the mapping with CUDA (cudaHostRegister) so
copies to the GPU run at pinned-memory bandwidth.
"""

import fcntl
import getpass
import json
import logging
import os
import re
import time
from typing import Dict, Optional

import torch

logger = logging.getLogger(__name__)

ALIGN = 256
_DTYPES = {str(d): d for d in (torch.float32, torch.float16, torch.bfloat16, torch.int8, torch.uint8,
                               torch.int32, torch.int64, torch.float8_e4m3fn, torch.float8_e5m2, torch.bool)}


def cache_root() -> str:
    return os.environ.get("PRISM_WEIGHT_CACHE_DIR", f"/dev/shm/prism_weights_{getpass.getuser()}")


def cache_dir(model_path: str, tp_rank: int = 0, tp_size: int = 1) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", model_path.strip("/"))
    return os.path.join(cache_root(), f"{name}__tp{tp_rank}of{tp_size}")


def exists(model_path: str, tp_rank: int = 0, tp_size: int = 1) -> bool:
    return os.path.exists(os.path.join(cache_dir(model_path, tp_rank, tp_size), "meta.json"))


def meta_nbytes(model_path: str, tp_rank: int = 0, tp_size: int = 1) -> int:
    """Bytes of one rank's cached weights, read from meta.json (no mapping, no CUDA)."""
    with open(os.path.join(cache_dir(model_path, tp_rank, tp_size), "meta.json")) as f:
        return int(json.load(f)["nbytes"])


def _device_tensors(model: torch.nn.Module):
    named = list(model.named_parameters()) + list(model.named_buffers())
    return [(n, t) for n, t in named if t.device.type == "cuda"]


def save(model: torch.nn.Module, model_path: str, tp_rank: int = 0, tp_size: int = 1) -> bool:
    """Write the model's GPU tensors to the cache (no-op if another process already did)."""
    d = cache_dir(model_path, tp_rank, tp_size)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(os.path.join(d, "meta.json")):
            return False
        tic = time.perf_counter()
        entries, aliases, by_ptr, offset = [], {}, {}, 0
        tensors = _device_tensors(model)
        for name, t in tensors:
            if t.data_ptr() in by_ptr and t.shape == by_ptr[t.data_ptr()][1].shape:
                aliases[name] = by_ptr[t.data_ptr()][0]
                continue
            by_ptr[t.data_ptr()] = (name, t)
            entries.append({"name": name, "dtype": str(t.dtype), "shape": list(t.shape), "offset": offset})
            offset += (t.numel() * t.element_size() + ALIGN - 1) // ALIGN * ALIGN
        flat = torch.from_file(os.path.join(d, "data.bin"), shared=True, size=max(offset, 1), dtype=torch.uint8)
        by_name = dict(tensors)
        for e in entries:
            t = by_name[e["name"]]
            n = t.numel() * t.element_size()
            flat[e["offset"]:e["offset"] + n].copy_(t.detach().contiguous().view(-1).view(torch.uint8))
        del flat
        tmp = os.path.join(d, "meta.json.tmp")
        with open(tmp, "w") as f:
            json.dump({"entries": entries, "aliases": aliases, "nbytes": offset}, f)
        os.rename(tmp, os.path.join(d, "meta.json"))
        logger.info(f"Prism weight cache: saved {model_path} ({offset / (1 << 30):.2f} GB) in "
                    f"{time.perf_counter() - tic:.2f}s to {d}")
        return True


class WeightCache:
    """A mapped, pinned cache of one model's tensors."""

    def __init__(self, model_path: str, tp_rank: int = 0, tp_size: int = 1):
        d = cache_dir(model_path, tp_rank, tp_size)
        meta = json.load(open(os.path.join(d, "meta.json")))
        self.entries, self.aliases = meta["entries"], meta["aliases"]
        self.nbytes = meta["nbytes"]
        self.flat = torch.from_file(os.path.join(d, "data.bin"), shared=True, size=max(self.nbytes, 1),
                                    dtype=torch.uint8)
        # Page-lock the mapping once per process: GPU copies from it then run at DMA bandwidth.
        rc = torch.cuda.cudart().cudaHostRegister(self.flat.data_ptr(), self.flat.numel(), 0)
        self.pinned = int(rc) == 0
        if not self.pinned:
            logger.warning(f"cudaHostRegister failed ({rc}); copies from {d} will be slower")
        self.tensors: Dict[str, torch.Tensor] = {}
        for e in self.entries:
            dtype = _DTYPES[e["dtype"]]
            n = dtype.itemsize
            for s in e["shape"]:
                n *= s
            self.tensors[e["name"]] = self.flat[e["offset"]:e["offset"] + n].view(dtype).view(e["shape"])

    def copy_into(self, model: torch.nn.Module) -> int:
        """Copy the cached tensors into a freshly initialized model of the same architecture."""
        named = dict(model.named_parameters())
        named.update(dict(model.named_buffers()))
        copied = 0
        for name, src in self.tensors.items():
            dst = named.get(name)
            if dst is None:
                raise KeyError(f"cached tensor {name} not in the model")
            if dst.shape != src.shape or dst.dtype != src.dtype:
                dst.data = torch.empty(src.shape, dtype=src.dtype, device=dst.device)
            dst.data.copy_(src, non_blocking=self.pinned)
            copied += src.numel() * src.element_size()
        for name, target in self.aliases.items():
            named[name].data = named[target].data
        torch.cuda.synchronize()
        return copied


_open: Dict[str, WeightCache] = {}


def open_cache(model_path: str, tp_rank: int = 0, tp_size: int = 1) -> Optional[WeightCache]:
    key = cache_dir(model_path, tp_rank, tp_size)
    if key not in _open:
        if not exists(model_path, tp_rank, tp_size):
            return None
        _open[key] = WeightCache(model_path, tp_rank, tp_size)
    return _open[key]
