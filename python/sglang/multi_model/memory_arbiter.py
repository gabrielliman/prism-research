"""Per-GPU memory arbiter shared by the Prism processes on one GPU (worker pool engines).

Prism runs several engines on one GPU. Each one grows its KV cache page by page (kvcached) and model
activations load whole weights, all deciding from free-memory snapshots taken independently. Two of them
can count the same free memory: the loser then fails (kvcached aborts the process on a failed page map;
a weight copy raises torch.OutOfMemoryError). The arbiter makes "check free memory, then take it" atomic
across processes and lets an activation reserve its weights before it starts copying them:

    arbiter = get_arbiter(gpu_id)
    if arbiter.try_reserve(nbytes):   # activation: hold the weights' memory while they are copied
        ...; arbiter.release()
    with arbiter.locked():            # KV growth: map pages only if they fit
        if arbiter.free_bytes() >= nbytes: map(...)

State lives in /dev/shm: a lock file (fcntl.flock) and a JSON file {pid: reserved bytes}. Reservations of
dead processes are ignored, so a crashed activation cannot leak them. free_bytes() is the device's free
memory minus the other processes' pending reservations and a headroom kept for allocations outside the
arbiter (activations, sampling buffers), PRISM_GPU_HEADROOM_GB (default: 5% of the GPU, as kvcached).
"""
import contextlib
import fcntl
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

import torch

logger = logging.getLogger(__name__)

_ARBITERS: Dict[int, "GPUMemoryArbiter"] = {}
STATS_LOG_INTERVAL_S = 30.0


class ActivationOutOfMemory(RuntimeError):
    """A model activation could not get the GPU memory it needs; the engine stays alive and deactivated."""


def get_arbiter(gpu_id: int) -> "GPUMemoryArbiter":
    if gpu_id not in _ARBITERS:
        _ARBITERS[gpu_id] = GPUMemoryArbiter(gpu_id)
    return _ARBITERS[gpu_id]


def _alive(pid: int) -> bool:
    """Whether the process runs. A killed child stays a zombie until its parent reaps it (the server only
    does at exit), and os.kill(pid, 0) still succeeds on a zombie, so check its state too."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            state = f.read().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, IndexError):
        return False
    return state not in ("Z", "X")


class GPUMemoryArbiter:
    def __init__(self, gpu_id: int, mem_get_info=None):
        self.gpu_id = gpu_id
        base = f"/dev/shm/prism_gpu{gpu_id}_{os.environ.get('USER', 'prism')}_arbiter"
        self.lock_path, self.state_path = base + ".lock", base + ".json"
        self.pid = os.getpid()
        self._mem_get_info = mem_get_info or (lambda: torch.cuda.mem_get_info(self.gpu_id))
        total = self._mem_get_info()[1]
        headroom_gb = os.environ.get("PRISM_GPU_HEADROOM_GB")
        self.headroom = int(float(headroom_gb) * (1 << 30)) if headroom_gb else int(total * 0.05)
        # flock excludes other processes; the RLock excludes the other threads of this one (kvcached's
        # preallocation thread maps pages too) and makes locked() re-entrant within a thread.
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._fd = None
        # Cost accounting, logged every STATS_LOG_INTERVAL_S: outermost lock acquisitions, time waiting for
        # the lock (other processes/threads holding it) and time holding it.
        self.stats = {"locks": 0, "wait_s": 0.0, "wait_max_s": 0.0, "hold_s": 0.0, "hold_max_s": 0.0}
        self._last_stats_log = time.monotonic()

    @contextlib.contextmanager
    def locked(self):
        """Exclusive across all processes and threads on this GPU (re-entrant within one thread)."""
        t0 = time.perf_counter()
        with self._thread_lock:
            outermost = self._depth == 0
            if outermost:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o666)
                fcntl.flock(self._fd, fcntl.LOCK_EX)
                t1 = time.perf_counter()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                    os.close(self._fd)
                    self._fd = None
                if outermost:
                    self._account(t1 - t0, time.perf_counter() - t1)

    def _account(self, wait: float, hold: float):
        st = self.stats
        st["locks"] += 1
        st["wait_s"] += wait
        st["hold_s"] += hold
        st["wait_max_s"] = max(st["wait_max_s"], wait)
        st["hold_max_s"] = max(st["hold_max_s"], hold)
        if time.monotonic() - self._last_stats_log >= STATS_LOG_INTERVAL_S:
            self._last_stats_log = time.monotonic()
            logger.info(
                f"Arbiter stats GPU {self.gpu_id} pid {self.pid}: locks {st['locks']}, "
                f"wait {st['wait_s'] * 1e3:.1f} ms (max {st['wait_max_s'] * 1e3:.2f} ms), "
                f"hold {st['hold_s'] * 1e3:.1f} ms (max {st['hold_max_s'] * 1e3:.2f} ms)"
            )

    def _read(self) -> Dict[int, int]:
        try:
            with open(self.state_path) as f:
                state = {int(k): int(v) for k, v in json.load(f).items()}
        except (FileNotFoundError, ValueError):
            state = {}
        return {pid: b for pid, b in state.items() if b > 0 and _alive(pid)}

    def _write(self, state: Dict[int, int]):
        tmp = f"{self.state_path}.{self.pid}"
        with open(tmp, "w") as f:
            json.dump({str(k): v for k, v in state.items()}, f)
        os.replace(tmp, self.state_path)

    def reserved_by_others(self) -> int:
        with self.locked():
            return sum(b for pid, b in self._read().items() if pid != self.pid)

    def free_bytes(self) -> int:
        """Free device memory this process may take: free minus others' reservations minus headroom."""
        with self.locked():
            free = self._mem_get_info()[0]
            return free - self.reserved_by_others() - self.headroom

    def try_reserve(self, nbytes: int) -> bool:
        """Reserve nbytes for this process if they are free now (replaces its previous reservation)."""
        with self.locked():
            # This process's own reservation is not allocated yet, so it is still part of the free memory.
            if self.free_bytes() < nbytes:
                return False
            state = self._read()
            state[self.pid] = nbytes
            self._write(state)
            return True

    def reserve_wait(self, nbytes: int, timeout: float, poll: float = 0.2) -> bool:
        start = time.monotonic()
        while True:
            if self.try_reserve(nbytes):
                self.last_reserve_wait_s = time.monotonic() - start
                return True
            if time.monotonic() - start >= timeout:
                self.last_reserve_wait_s = time.monotonic() - start
                return False
            time.sleep(poll)

    def release(self):
        with self.locked():
            state = self._read()
            if state.pop(self.pid, None) is not None:
                self._write(state)

    def reservations(self) -> Dict[int, int]:
        with self.locked():
            return self._read()


def get_arbiter_or_none(gpu_id: Optional[int]) -> Optional[GPUMemoryArbiter]:
    """The GPU's arbiter if PRISM_MEMORY_ARBITER=1. Off by default: the arbiter, kvcached_patches and the
    activation reservation change how the engines share memory even when nothing fails, so Prism as published
    is compared without them."""
    if gpu_id is None or os.environ.get("PRISM_MEMORY_ARBITER", "0") != "1":
        return None
    return get_arbiter(gpu_id)


def _worker_pid_path(gpu_id: int, worker_id: int) -> str:
    return f"/dev/shm/prism_gpu{gpu_id}_worker{worker_id}_{os.environ.get('USER', 'prism')}.pid"


def write_worker_pid(gpu_id: int, worker_id: int):
    """Worker pool engines record their PID so that the GPU scheduler can tell when one has died."""
    with open(_worker_pid_path(gpu_id, worker_id), "w") as f:
        f.write(str(os.getpid()))


def worker_alive(gpu_id: int, worker_id: int) -> Optional[bool]:
    """True/False if the worker registered a PID, None if it has not (yet)."""
    try:
        with open(_worker_pid_path(gpu_id, worker_id)) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None
    return _alive(pid)
