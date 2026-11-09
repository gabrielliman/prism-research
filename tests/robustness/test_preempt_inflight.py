"""P16 (F6.P16, 2026-11-09): a preempting deactivation must retract the request half-way through a chunked prefill.

Before the fix, Scheduler._retract_running_batch_normal filtered the in-flight chunked request (current_inflight_req)
out of the last prefill batch and then dropped it: it was not in the BatchRetractDecodeReq (the controller's
ModelQueueTracker kept it RUNNING on a model that had left) nor in the waiting queue (never sent back to the
frontend, never answered), and current_inflight_req survived into the worker's next activation.

The real methods are taken from scheduler.py's source (importing the module needs the whole SGLang/GPU stack) and
run on a fake scheduler; the real ModelQueueTracker (SGLang types stubbed) receives the messages they send.
Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/robustness/test_preempt_inflight.py
"""
import ast
import logging
import os
import sys
import time
import types
import unittest
from typing import Optional

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python")
SRC = os.path.join(ROOT, "sglang", "srt", "managers", "scheduler.py")
METHODS = ("_retract_running_batch_normal", "_take_inflight_req")


class BatchRetractDecodeReq:
    def __init__(self, rids, len_output_ids, model, retract_time):
        self.rids, self.len_output_ids, self.model, self.retract_time = rids, len_output_ids, model, retract_time


class BatchRunReq:
    def __init__(self, rids, model, run_time, gpu_id):
        self.rids, self.model, self.run_time, self.gpu_id = rids, model, run_time, gpu_id


def _load_methods():
    tree = ast.parse(open(SRC).read())
    cls = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Scheduler")
    fns = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in METHODS]
    assert len(fns) == len(METHODS), [f.name for f in fns]
    for f in fns:
        f.decorator_list = []
    ns = {"os": os, "time": time, "Optional": Optional, "logger": logging.getLogger("t"), "TRACE_RIDS": False,
          "BatchRetractDecodeReq": BatchRetractDecodeReq}
    exec(compile(ast.Module(body=fns, type_ignores=[]), SRC, "exec"), ns)
    return {name: ns[name] for name in METHODS}


def _load_tracker():
    for name in ["sglang", "sglang.srt", "sglang.srt.managers", "sglang.multi_model",
                 "sglang.multi_model.scheduling"]:
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = [os.path.join(ROOT, *name.split("."))]
            sys.modules[name] = m
    io = sys.modules.get("sglang.srt.managers.io_struct") or types.ModuleType("sglang.srt.managers.io_struct")
    for k in ("BatchRetractDecodeReq", "BatchRunReq", "FinishReq", "GenerateReqInput"):
        if not hasattr(io, k):
            setattr(io, k, type(k, (), {}))
    sys.modules["sglang.srt.managers.io_struct"] = io
    from sglang.multi_model.scheduling import model_queue_tracker as mqt
    return mqt


M = _load_methods()
mqt = _load_tracker()


class Req:
    def __init__(self, rid):
        self.rid, self.output_ids = rid, []
        self.prefix_indices, self.last_node, self.extend_input_len = [1, 2], "node", 8192
        self.last_update_decode_tokens, self.logprob_start_len, self.is_inflight_req = 0, 0, 0
        self.req_pool_idx = 7


class Mode:
    def __init__(self, decode):
        self._decode = decode

    def is_decode(self):
        return self._decode


class Batch:
    def __init__(self, reqs, decode=False):
        self.reqs, self.forward_mode = list(reqs), Mode(decode)

    def filter_batch(self, current_inflight_req=None):
        self.reqs = [r for r in self.reqs if r is not current_inflight_req]

    def is_empty(self):
        return not self.reqs

    def merge_batch(self, other):
        self.reqs += other.reqs


class Fake:
    """The state a worker is in when a preempting deactivation arrives right after a prefill batch whose last
    request was chunked (it is current_inflight_req and still in last_batch)."""

    def __init__(self, decode_last=False):
        self.a, self.r = Req("a"), Req("r")
        self.a.output_ids = [5]
        self.current_inflight_req = self.r
        self.last_batch = Batch([self.a], decode=True) if decode_last else Batch([self.a, self.r])
        self.running_batch = None
        self.waiting_queue = []
        self.use_kvcached_v0 = False
        self.batch_is_full = True
        self.model_config = types.SimpleNamespace(name="model_9")
        self.sent, self.freed, self.unlocked = [], [], []
        self.send_to_controller = types.SimpleNamespace(send_pyobj=self.sent.append)
        self.tree_cache = types.SimpleNamespace(cache_unfinished_req=lambda req: None,
                                                dec_lock_ref=self.unlocked.append)
        self.req_to_token_pool = types.SimpleNamespace(free=self.freed.append)

    def _take_inflight_req(self):
        return M["_take_inflight_req"](self)

    def retract(self):
        M["_retract_running_batch_normal"](self)


def tracker_after(fake):
    """The controller's view: both requests started (BatchRunReq), then the worker's retraction message."""
    q = mqt.ModelQueueTracker("model_9")
    for rid in ("a", "r"):
        req = mqt.Req(rid=rid, arrival_time=0.0, model="model_9", output_len=10)
        q.received_reqs[rid] = req
        q.waiting_reqs.append(req)
    q.start_running_reqs(BatchRunReq(rids=["a", "r"], model="model_9", run_time=time.time() - 1, gpu_id=0))
    for msg in fake.sent:
        q.preempt_reqs(msg)
    return q


class PreemptInflightTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("PRISM_DEACTIVATE_REQUEUE_INFLIGHT", None)

    def test_inflight_is_retracted_and_requeued(self):
        f = Fake()
        f.retract()
        self.assertEqual(f.sent[0].rids, ["a", "r"])
        self.assertEqual([x.rid for x in f.waiting_queue], ["a", "r"])  # _evict_all_waiting_requests sends both
        self.assertIsNone(f.current_inflight_req)
        self.assertEqual(f.freed, [7])  # its KV slot freed once, by the existing merge
        self.assertEqual(f.unlocked, ["node"])  # the tree-cache lock taken by cache_unfinished_req released
        self.assertEqual((f.r.prefix_indices, f.r.last_node, f.r.extend_input_len), ([], None, 0))

    def test_inflight_after_decode_batch(self):
        # a chunk postponed (no KV) and a decode step ran: last_batch is decode, the KV slot was freed earlier
        f = Fake(decode_last=True)
        f.retract()
        self.assertEqual(f.sent[0].rids, ["r"])  # running batch empty here; only the inflight request
        self.assertEqual(f.freed, [])
        self.assertIsNone(f.current_inflight_req)

    def test_controller_has_no_stale_running(self):
        f = Fake()
        f.retract()
        q = tracker_after(f)
        self.assertEqual(q.get_num_running_reqs(), 0)
        self.assertEqual(sorted(r.rid for r in q.waiting_reqs), ["a", "r"])

    def test_old_behaviour_leaves_stale_running(self):
        os.environ["PRISM_DEACTIVATE_REQUEUE_INFLIGHT"] = "0"
        f = Fake()
        f.retract()
        self.assertEqual(f.sent[0].rids, ["a"])
        self.assertEqual([x.rid for x in f.waiting_queue], ["a"])  # r never goes back to the frontend
        self.assertIs(f.current_inflight_req, f.r)  # and leaks into the next activation
        q = tracker_after(f)
        self.assertEqual([r.rid for r in q.running_reqs], ["r"])  # P16: RUNNING on a model that left

    def test_nothing_inflight(self):
        f = Fake()
        f.current_inflight_req = None
        f.last_batch = Batch([f.a])
        f.retract()
        self.assertEqual(f.sent[0].rids, ["a"])
        self.assertEqual(f.unlocked, [])


if __name__ == "__main__":
    unittest.main()
