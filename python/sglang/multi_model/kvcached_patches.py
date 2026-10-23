"""Prism's fixes to kvcached (prism/shm branch) under memory pressure, applied at run time.

kvcached maps KV pages with CHECK_DRV, which calls abort() when cuMemCreate/cuMemMap/cuMemSetAccess fail:
a page map that does not fit kills the whole engine process, and Prism keeps routing requests to it. The
map is preceded only by a free-memory snapshot (available_size), taken independently by every engine on
the GPU, so two engines can count the same free memory. These patches replace kvcached's Python
allocation paths so that a page is mapped only after checking, under the GPU's memory arbiter lock
(memory_arbiter.py), that it fits:

  PageAllocator.alloc_page      page does not fit -> page back to the free list, KVMemoryUnavailable
  PageAllocator._prealloc_worker  pre-mapping of reserved pages skips what does not fit
  KVCacheManager.alloc          KVMemoryUnavailable -> blocks taken by this call are freed, returns None
                                (what kvcached already returns when available_size is too small)
  KVCacheManager._physical_free_size  free memory minus pending activation reservations (arbiter)

Applied by the worker pool model runner before its first KV pool (apply(gpu_id)), only with
PRISM_MEMORY_ARBITER=1 (off by default: kvcached runs as published).
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

_APPLIED = False


class KVMemoryUnavailable(Exception):
    """The KV pages asked for do not fit in the GPU's free memory now."""


def apply(gpu_id: int):
    global _APPLIED
    from sglang.multi_model.memory_arbiter import get_arbiter_or_none

    arbiter = get_arbiter_or_none(gpu_id)
    if _APPLIED or arbiter is None:
        return
    from kvcached import slab_allocator as sa

    def _guarded_map(allocator, page_ids: List[int]):
        """Map these pages (all layers, K and V) only if they fit; else KVMemoryUnavailable."""
        nbytes = len(page_ids) * allocator.page_size_all_layers
        with arbiter.locked():
            if arbiter.free_bytes() < nbytes:
                raise KVMemoryUnavailable(f"{nbytes / (1 << 20):.0f} MiB of KV pages do not fit")
            sa.map_to_kv_tensors([pid * allocator.page_size for pid in page_ids])

    def alloc_page(self):
        # Fast path: allocate from reserved pages (already mapped)
        page_id = None
        with self.prealloc_lock:
            if self.reserved_page_list:
                page_id = self.reserved_page_list.pop()
                if len(self.reserved_page_list) < self.min_reserved_pages:
                    self.prealloc_needed = True
                    self.prealloc_cond.notify()
        if page_id is not None:
            return sa.Page(page_id, self.page_size)

        # Slow path: allocate from free list and map it, if it fits
        with self.prealloc_lock:
            if not self.free_page_list:
                raise ValueError("No free page available")
            page_id = self.free_page_list.popleft()
        try:
            _guarded_map(self, [page_id])
        except KVMemoryUnavailable:
            with self.prealloc_lock:
                self.free_page_list.appendleft(page_id)
            raise
        if self.shm is not None:
            self.memory_in_use[0] += self.page_size_all_layers
        self._trigger_preallocation()
        return sa.Page(page_id, self.page_size)

    def _prealloc_worker(self):
        """Pre-maps up to min_reserved_pages pages, as kvcached does, skipping the ones that do not fit."""
        while self.prealloc_running:
            with self.prealloc_lock:
                while not self.prealloc_needed and self.prealloc_running:
                    self.prealloc_cond.wait()
                if not self.prealloc_running:
                    break
                self.prealloc_needed = False
                to_reserve = max(0, self.min_reserved_pages - len(self.reserved_page_list))
                to_reserve = min(to_reserve, len(self.free_page_list))
                pages = [self.free_page_list.popleft() for _ in range(to_reserve)]
            mapped = []
            for pid in pages:  # one by one: map what fits
                try:
                    _guarded_map(self, [pid])
                    mapped.append(pid)
                except KVMemoryUnavailable:
                    break
            with self.prealloc_lock:
                self.free_page_list.extendleft(p for p in pages if p not in mapped)
                self.reserved_page_list.extend(mapped)
            if mapped and self.shm is not None:
                self.memory_in_use[0] += len(mapped) * self.page_size_all_layers

    def kv_alloc(self, need_size: int):
        if self.available_size() < need_size:
            return None
        taken: List[int] = []
        try:
            return _kv_alloc(self, need_size, taken)
        except KVMemoryUnavailable as e:
            if taken:
                self.free(taken)
            logger.warning(f"KV allocation of {need_size} tokens refused: {e}")
            return None

    def _kv_alloc(self, need_size: int, taken: List[int]):
        # kvcached's KVCacheManager.alloc, recording in `taken` what it has handed out so far
        remaining_need = need_size
        if self.reserved_blocks:
            if len(self.reserved_blocks) >= remaining_need:
                taken.extend(self.reserved_blocks[:remaining_need])
                self.reserved_blocks = self.reserved_blocks[remaining_need:]
                remaining_need = 0
            else:
                taken.extend(self.reserved_blocks)
                remaining_need -= len(self.reserved_blocks)
                self.reserved_blocks = []
        while remaining_need > 0:
            if not self.avail_pages:
                page = self.page_allocator.alloc_page()
                page.init(self.block_mem_size)
                self.num_avail_blocks += page.num_free_blocks()
            else:
                _, page = self.avail_pages.popitem()
            if page.num_free_blocks() > remaining_need:
                self.num_avail_blocks -= remaining_need
                taken.extend(page.free_list[:remaining_need])
                page.free_list = page.free_list[remaining_need:]
                remaining_need = 0
                self.avail_pages[page.page_id] = page
            else:
                self.num_avail_blocks -= page.num_free_blocks()
                taken.extend(page.free_list)
                remaining_need -= len(page.free_list)
                page.free_list = []
                self.full_pages[page.page_id] = page
        return list(taken)

    def _physical_free_size(self) -> int:
        avail = max(arbiter.free_bytes(), 0)
        avail_pages = avail // sa.PAGE_SIZE
        return (avail_pages // self.num_layers // 2) * (sa.PAGE_SIZE // self.block_mem_size)

    sa.PageAllocator.alloc_page = alloc_page
    sa.PageAllocator._prealloc_worker = _prealloc_worker
    sa.KVCacheManager.alloc = kv_alloc
    sa.KVCacheManager._physical_free_size = _physical_free_size
    _APPLIED = True
    logger.info(f"kvcached patched: KV pages are mapped under GPU {gpu_id}'s memory arbiter")
