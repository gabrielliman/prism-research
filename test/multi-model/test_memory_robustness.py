"""Unit tests for Prism's GPU memory arbiter and its kvcached fixes, without a GPU.

    python3 test/multi-model/test_memory_robustness.py [-v]

The device is simulated: a fake torch.cuda.mem_get_info backed by a byte counter in shared memory, and a
fake kvcached.vmm_ops whose map_to_kv_tensors takes bytes from that counter and fails, like CUDA, when they
do not fit (the real C++ then calls abort()). kvcached's own slab_allocator.py is loaded from KVCACHED_SRC
(default: /sgl-workspace/kvcached, else ../kvcached next to this repository).
"""
import importlib.util
import multiprocessing as mp
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KVCACHED_SRC = os.environ.get("KVCACHED_SRC") or next(
    (p for p in ("/sgl-workspace/kvcached", os.path.join(os.path.dirname(ROOT), "kvcached")) if os.path.isdir(p)),
    None,
)

GB, MB = 1 << 30, 1 << 20
TOTAL = 80 * GB
_DEV = mp.Array("q", [TOTAL], lock=True)  # free bytes of the simulated device, shared by processes


def _mem_get_info(*_):
    return (_DEV[0], TOTAL)


class _MapFailure(RuntimeError):
    pass


def _install_stubs():
    """Fake torch (mem_get_info only), fake kvcached.vmm_ops and the Prism modules under test."""
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(mem_get_info=_mem_get_info)
    sys.modules.setdefault("torch", torch)

    state = {"page_bytes": None, "mapped": 0}

    def map_to_kv_tensors(offsets):
        need = len(offsets) * state["page_bytes"]
        with _DEV.get_lock():
            if _DEV[0] < need:
                raise _MapFailure(f"cuMemCreate out of memory ({need} > {_DEV[0]})")  # real kvcached: abort()
            _DEV[0] -= need
        state["mapped"] += need

    def unmap_from_kv_tensors(offsets):
        freed = len(offsets) * state["page_bytes"]
        with _DEV.get_lock():
            _DEV[0] += freed
        state["mapped"] -= freed

    vmm = types.ModuleType("kvcached.vmm_ops")
    vmm.map_to_kv_tensors, vmm.unmap_from_kv_tensors = map_to_kv_tensors, unmap_from_kv_tensors
    kv = types.ModuleType("kvcached")
    kv.__path__ = [os.path.join(KVCACHED_SRC, "kvcached")]
    sys.modules.update({"kvcached": kv, "kvcached.vmm_ops": vmm})

    for name in ("sglang", "sglang.multi_model"):
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules.setdefault(name, mod)
    for name in ("memory_arbiter", "kvcached_patches"):
        path = os.path.join(ROOT, "python", "sglang", "multi_model", f"{name}.py")
        spec = importlib.util.spec_from_file_location(f"sglang.multi_model.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return state


def _reserve_in_child(args):
    gpu_id, nbytes = args
    from sglang.multi_model.memory_arbiter import GPUMemoryArbiter

    arbiter = GPUMemoryArbiter(gpu_id, mem_get_info=_mem_get_info)
    return arbiter.try_reserve(nbytes)


def _reserve_and_hold(gpu_id, nbytes, results, start, done):
    """One engine: reserve when all start together, report, and stay alive (a dead process's reservation
    no longer counts) until the test is done."""
    start.wait()
    results.put(_reserve_in_child((gpu_id, nbytes)))
    done.wait()


@unittest.skipIf(KVCACHED_SRC is None, "kvcached sources not found (set KVCACHED_SRC)")
class TestMemoryRobustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["USER"] = f"test{os.getpid()}"  # private /dev/shm files
        os.environ["PRISM_GPU_HEADROOM_GB"] = "1"
        os.environ["PRISM_MEMORY_ARBITER"] = "1"  # off by default in Prism
        cls.vmm = _install_stubs()
        from kvcached import slab_allocator as sa

        cls.sa = sa
        cls.original = {
            "alloc_page": sa.PageAllocator.alloc_page,
            "_prealloc_worker": sa.PageAllocator._prealloc_worker,
            "alloc": sa.KVCacheManager.alloc,
            "_physical_free_size": sa.KVCacheManager._physical_free_size,
        }

    def setUp(self):
        _DEV[0] = TOTAL
        self.gpu_id = int.from_bytes(os.urandom(2), "little")  # fresh arbiter files per test
        import sglang.multi_model.kvcached_patches as kp
        import sglang.multi_model.memory_arbiter as ma

        ma._ARBITERS.clear()
        ma._ARBITERS[self.gpu_id] = ma.GPUMemoryArbiter(self.gpu_id, mem_get_info=_mem_get_info)
        self.ma, self.kp = ma, kp
        for k, v in self.original.items():  # each test chooses patched or original kvcached
            setattr(self.sa.PageAllocator if k in ("alloc_page", "_prealloc_worker") else self.sa.KVCacheManager, k, v)
        kp._APPLIED = False

    def _manager(self, num_layers=32, num_tokens=2_000_000):
        # Llama-3.1-8B-like: 32 layers, 16 tokens per block of 2 KiB per layer and K/V
        mgr = self.sa.KVCacheManager(num_blocks=num_tokens // 16, block_size=16, cell_size=2048,
                                     num_layers=num_layers)
        self.vmm["page_bytes"] = mgr.page_allocator.page_size_all_layers
        return mgr

    def test_arbiter_reservations_are_atomic_across_processes(self):
        # 16 processes try to reserve 15 GB each at once on 80 GB free (1 GB headroom): exactly 5 may succeed
        ctx = mp.get_context("fork")
        results, start, done = ctx.Queue(), ctx.Event(), ctx.Event()
        procs = [ctx.Process(target=_reserve_and_hold, args=(self.gpu_id, 15 * GB, results, start, done))
                 for _ in range(16)]
        for p in procs:
            p.start()
        start.set()
        ok = [results.get(timeout=30) for _ in procs]
        done.set()
        for p in procs:
            p.join()
        self.assertEqual(sum(ok), 5)

    def test_arbiter_ignores_reservations_of_dead_processes(self):
        arbiter = self.ma.get_arbiter(self.gpu_id)
        state = {999999: 50 * GB, os.getpid(): 0}
        arbiter._write(state)
        self.assertEqual(arbiter.reserved_by_others(), 0)

    def test_killed_worker_is_dead_even_as_a_zombie(self):
        # A worker killed with -9 stays a zombie until the server reaps it; it must count as dead.
        pid = os.fork()
        if pid == 0:
            __import__("time").sleep(30)
            os._exit(0)
        self.assertTrue(self.ma._alive(pid))
        os.kill(pid, 9)
        __import__("time").sleep(0.2)
        self.assertFalse(self.ma._alive(pid))  # zombie: not reaped yet
        os.waitpid(pid, 0)

    def test_pending_activation_hides_memory_from_kv_growth(self):
        self.kp.apply(self.gpu_id)
        mgr = self._manager()
        other = mp.get_context("fork").Process(target=lambda: (_reserve_in_child((self.gpu_id, 70 * GB)),
                                                               __import__("time").sleep(3)))
        other.start()
        __import__("time").sleep(1)
        # 80 GB free, 70 GB reserved by a live activation, 1 GB headroom: the KV pool sees ~9 GB, not ~79 GB
        avail_gb = mgr.available_size() * mgr.block_mem_size * 32 * 2 / GB
        other.join()
        self.assertLess(avail_gb, 10)

    def test_original_kvcached_maps_beyond_free_memory(self):
        # Documents the bug: available_size is a snapshot; if memory goes away before the map, kvcached maps
        # anyway and the driver fails (the real C++ aborts the process).
        mgr = self._manager()
        __import__("time").sleep(0.2)  # let the prealloc thread map its pages
        blocks_per_page = mgr.page_allocator.page_size // mgr.block_mem_size
        need = (len(mgr.page_allocator.reserved_page_list) + 2) * blocks_per_page  # needs new pages
        _DEV[0] = 40 * GB
        check = mgr.available_size

        def available_then_taken():  # the snapshot says yes, then another engine takes the memory
            n = check()
            _DEV[0] = 0
            return n

        mgr.available_size = available_then_taken
        with self.assertRaises(_MapFailure):
            mgr.alloc(need)

    def test_patched_alloc_refuses_instead_of_failing(self):
        self.kp.apply(self.gpu_id)
        mgr = self._manager()
        __import__("time").sleep(0.2)  # let the prealloc thread map its pages
        free_before = _DEV[0]
        got = mgr.alloc(16)
        self.assertIsNotNone(got)  # fits: served from a mapped page
        __import__("time").sleep(0.2)  # let the prealloc thread refill the page alloc() used
        _DEV[0] = 0  # all the remaining memory went to another engine
        pa = mgr.page_allocator
        pages_before = len(pa.free_page_list) + len(pa.reserved_page_list)
        mgr.available_size = lambda: 10**9  # the snapshot says yes
        self.assertIsNone(mgr.alloc(100 * 64))  # needs new pages: refused, no exception
        __import__("time").sleep(0.2)  # the prealloc thread, woken by the refused call, gives its pages back
        self.assertEqual(len(pa.free_page_list) + len(pa.reserved_page_list), pages_before)  # no page leaked
        mgr.free(got)
        self.assertLessEqual(_DEV[0], free_before)

    def test_patched_alloc_rolls_back_partial_allocations(self):
        self.kp.apply(self.gpu_id)
        mgr = self._manager()
        __import__("time").sleep(0.2)
        mapped_pages = len(mgr.page_allocator.reserved_page_list)
        blocks_per_page = mgr.page_allocator.page_size // mgr.block_mem_size
        _DEV[0] = 1 * GB + mgr.page_allocator.page_size_all_layers  # room for one more page past headroom
        need = (mapped_pages + 3) * blocks_per_page  # more than mapped + 1 page
        # bypass available_size (snapshot said yes) to exercise the mid-allocation refusal
        mgr.available_size = lambda: 10**9
        self.assertIsNone(mgr.alloc(need))
        self.assertEqual(mgr.num_avail_blocks + len(mgr.reserved_blocks), sum(
            p.num_free_blocks() for p in mgr.avail_pages.values()))
        self.assertEqual(len(mgr.full_pages), 0)  # every block taken by the failed call was given back

    def test_prealloc_thread_skips_pages_that_do_not_fit(self):
        self.kp.apply(self.gpu_id)
        _DEV[0] = 1 * GB  # only the headroom: nothing fits
        mgr = self._manager()
        __import__("time").sleep(0.3)
        self.assertEqual(len(mgr.page_allocator.reserved_page_list), 0)
        self.assertEqual(_DEV[0], 1 * GB)  # nothing mapped, thread still alive
        self.assertTrue(mgr.page_allocator.prealloc_thd.is_alive())


if __name__ == "__main__":
    unittest.main()
