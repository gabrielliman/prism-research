"""D59: the GPU scheduler answers each controller command once, with the command's rid, and drops the engine's late
answers to older commands (gpu/gpu_scheduler.py Command, _answers_current, _send_event).

The GPU scheduler is imported with its heavy dependencies stubbed (zmq is real); a fake worker pool, Redis and
request-handler socket drive the message orders seen on the node: evicted while loading, re-activated while leaving,
deactivated with no worker, activated again while still loading.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_gpu_scheduler_commands.py
"""
import dataclasses
import importlib.util
import multiprocessing.connection  # noqa: F401  (gpu_scheduler annotates with mp.connection)
import os
import sys
import types
import unittest
import uuid
from typing import Optional
from unittest import mock

import zmq

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python")
GS_PATH = os.path.join(ROOT, "sglang", "multi_model", "scheduling", "gpu", "gpu_scheduler.py")
CONSTANTS_PATH = os.path.join(ROOT, "sglang", "multi_model", "scheduling", "constants.py")


@dataclasses.dataclass
class ActivateReqInput:
    model_name: str
    gpu_id: int
    instance_idx: Optional[int] = 0
    rid: Optional[str] = None
    memory_pool_size: Optional[float] = None

    def __post_init__(self):
        self.rid = self.rid or uuid.uuid4().hex


@dataclasses.dataclass
class DeactivateReqInput:
    model_name: str
    gpu_id: Optional[int] = None
    instance_idx: Optional[int] = 0
    rid: Optional[str] = None

    def __post_init__(self):
        self.rid = self.rid or uuid.uuid4().hex


@dataclasses.dataclass
class ActivateReqOutput:
    rid: str
    success: bool
    model_name: str
    instance_idx: Optional[int] = 0
    memory_usage: object = None


@dataclasses.dataclass
class DeactivateReqOutput:  # not a subclass: the GPU scheduler dispatches on isinstance
    rid: str
    success: bool
    model_name: str
    instance_idx: Optional[int] = 0
    memory_usage: object = None


def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m


def _load_gpu_scheduler():
    spec = importlib.util.spec_from_file_location("constants_d59", CONSTANTS_PATH)
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)
    stub = lambda *a, **kw: None  # noqa: E731
    modules = {
        "sglang": _module("sglang"), "sglang.multi_model": _module("sglang.multi_model"),
        "sglang.multi_model.scheduling": _module("sglang.multi_model.scheduling"),
        "sglang.multi_model.scheduling.gpu": _module("sglang.multi_model.scheduling.gpu"),
        "sglang.multi_model.memory_arbiter": _module("x", model_service_alive=stub),
        "sglang.multi_model.multi_model_server_args": _module("x", MultiModelServerArgs=object),
        "sglang.multi_model.scheduling.constants": constants,
        "sglang.multi_model.scheduling.gpu.request_queue": _module("x", RequestQueue=object),
        "sglang.multi_model.scheduling.gpu.resource_manager": _module("x", ResourceManager=object),
        "sglang.multi_model.scheduling.gpu.worker_pool": _module("x", WorkerPool=object),
        "sglang.multi_model.utils": _module("sglang.multi_model.utils"),
        "sglang.multi_model.utils.get_memory_pool_size": _module("x", get_model_path_to_cell_size=stub),
        "sglang.srt": _module("sglang.srt"), "sglang.srt.managers": _module("sglang.srt.managers"),
        "sglang.srt.managers.io_struct": _module(
            "x", ActivateReqInput=ActivateReqInput, ActivateReqOutput=ActivateReqOutput,
            DeactivateReqInput=DeactivateReqInput, DeactivateReqOutput=DeactivateReqOutput, GenerateReqInput=object),
        "sglang.srt.redis_utils": _module("x", RedisClient=object),
        "sglang.srt.utils": _module("x", configure_logger=stub, kill_parent_process=stub),
        "sglang.utils": _module("x", cleanup_zmq_ipc=stub, get_exception_traceback=lambda: ""),
    }
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("gpu_scheduler_d59", GS_PATH)
        gs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gs)
    return gs


gs = _load_gpu_scheduler()


class FakeRedis:
    def __init__(self):
        self.lists = {}

    def send_pyobj(self, key, obj):
        self.lists.setdefault(key, []).append(obj)

    def pop_all(self, key):
        return self.lists.pop(key, [])


class FakeSocket:
    def __init__(self):
        self.inbox = []

    def recv_pyobj(self, flags=0):
        if not self.inbox:
            raise zmq.ZMQError()
        return self.inbox.pop(0)


class FakeWorkerPool:
    """As gpu/worker_pool.py: one model per worker; requests reach the worker's engine in order."""

    def __init__(self, workers=2):
        self._free_workers = list(range(workers))
        self._model_to_worker = {}
        self.sent = []  # (worker, request) in the order the engines get them

    def handle_activate_model(self, req):
        if req.model_name in self._model_to_worker or not self._free_workers:
            return False
        self._model_to_worker[req.model_name] = self._free_workers.pop(0)
        self.sent.append((self._model_to_worker[req.model_name], req))
        return True

    def handle_deactivate_model(self, req):
        if req.model_name not in self._model_to_worker:
            return False
        worker = self._model_to_worker.pop(req.model_name)
        self._free_workers.append(worker)
        self.sent.append((worker, req))
        return True

    def cleanup(self):
        pass

    def release_worker(self, model_name):
        self._free_workers.append(self._model_to_worker.pop(model_name))


def scheduler():
    s = gs.GPUScheduler.__new__(gs.GPUScheduler)
    s.gpu_id = 0
    s._model_states, s._commands = {}, {}
    s.server_args = types.SimpleNamespace(enable_worker_pool=True, engine_to_gpu_scheduler_key_prefix="e2g",
                                          frontend_generate_request_key_prefix="fe",
                                          backend_generate_request_key_prefix="be")
    s.redis_client, s.recv_from_request_handler, s.worker_pool = FakeRedis(), FakeSocket(), FakeWorkerPool()
    s.resource_manager = types.SimpleNamespace(add_active_model=lambda m: None, remove_active_model=lambda m: None)
    s.queue = types.SimpleNamespace(pop_model_requests=lambda m: [], clear_activating_usage=lambda m: None)
    return s


def command(s, req):
    s.recv_from_request_handler.inbox.append(req)
    s._recv_from_request_handler()


def engine_answers(s, req, success=True):
    out = (ActivateReqOutput if isinstance(req, ActivateReqInput) else DeactivateReqOutput)(
        rid=req.rid, success=success, model_name=req.model_name)
    s.redis_client.send_pyobj("e2g:0", out)
    s._recv_from_engine()


def events(s):
    return [(e["event"], e["rid"]) for e in s.redis_client.pop_all("e2g:controller_events")]


class GPUSchedulerCommandsTest(unittest.TestCase):
    def test_evicted_while_loading_then_activated_again(self):
        s = scheduler()
        a1, d1, a2 = ActivateReqInput("m", 0, rid="a1"), DeactivateReqInput("m", 0, rid="d1"), \
            ActivateReqInput("m", 0, rid="a2")
        for req in (a1, d1, a2):
            command(s, req)
        engine_answers(s, a1)  # the first load ends after both newer commands
        engine_answers(s, d1)
        self.assertEqual(events(s), [])  # neither confirms the activation a2
        self.assertEqual(s._model_states["m"], "activating")
        engine_answers(s, a2)
        self.assertEqual(events(s), [("model_activated", "a2")])
        self.assertEqual(s._model_states["m"], "activated")

    def test_late_failure_does_not_release_the_new_worker(self):
        s = scheduler()
        a1, d1, a2 = ActivateReqInput("m", 0, rid="a1"), DeactivateReqInput("m", 0, rid="d1"), \
            ActivateReqInput("m", 0, rid="a2")
        for req in (a1, d1, a2):
            command(s, req)
        worker = s.worker_pool._model_to_worker["m"]
        engine_answers(s, a1, success=False)
        self.assertEqual(events(s), [])
        self.assertEqual(s.worker_pool._model_to_worker.get("m"), worker)

    def test_failed_deactivation_ends_the_transition_on_both_sides(self):
        s = scheduler()
        a1, d1 = ActivateReqInput("m", 0, rid="a1"), DeactivateReqInput("m", 0, rid="d1")
        command(s, a1)
        engine_answers(s, a1)
        command(s, d1)
        engine_answers(s, d1, success=False)  # "Scheduler is already deactivated"
        evs = s.redis_client.pop_all("e2g:controller_events")
        self.assertEqual([(e["event"], e["rid"], e.get("reason")) for e in evs][-1],
                         ("model_deactivated", "d1", "already_inactive"))
        self.assertEqual(s._model_states["m"], "deactivated")  # no longer stuck in "deactivating"

    def test_deactivation_without_worker_is_answered_at_once(self):
        s = scheduler()
        command(s, DeactivateReqInput("m", 0, rid="d1"))
        evs = s.redis_client.pop_all("e2g:controller_events")
        self.assertEqual([(e["event"], e["rid"], e["success"], e["reason"]) for e in evs],
                         [("model_deactivated", "d1", False, "not_served")])

    def test_activation_while_still_loading_waits_for_the_load(self):
        s = scheduler()
        a1, a2 = ActivateReqInput("m", 0, rid="a1"), ActivateReqInput("m", 0, rid="a2")
        command(s, a1)
        command(s, a2)  # the worker already has m, still loading
        self.assertEqual(events(s), [])  # not reported active before it is
        engine_answers(s, a1)
        self.assertEqual(events(s), [("model_activated", "a2")])

    def test_activation_of_a_served_model_is_answered_at_once(self):
        s = scheduler()
        a1, a2 = ActivateReqInput("m", 0, rid="a1"), ActivateReqInput("m", 0, rid="a2")
        command(s, a1)
        engine_answers(s, a1)
        events(s)
        command(s, a2)
        self.assertEqual(events(s), [("model_activated", "a2")])

    def test_loss_carries_the_current_command(self):
        s = scheduler()
        a1 = ActivateReqInput("m", 0, rid="a1")
        command(s, a1)
        engine_answers(s, a1)
        events(s)
        s._on_model_lost("m", "worker died", release_worker=False)
        self.assertEqual(events(s), [("model_lost", "a1")])

    def test_no_worker_is_a_loss_of_that_command(self):
        s = scheduler()
        s.worker_pool._free_workers.clear()
        command(s, ActivateReqInput("m", 0, rid="a1"))
        self.assertEqual(events(s), [("model_lost", "a1")])


if __name__ == "__main__":
    unittest.main()
