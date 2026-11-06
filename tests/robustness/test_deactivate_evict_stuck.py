"""P13 (F6a triage, 2026-11-04): a deactivation without preemption must not wait forever for requests it cannot run.

The real Scheduler._run_to_completion_normal is taken from scheduler.py's source (importing the module needs the
whole SGLang/GPU stack) and run on a fake scheduler whose only request was retracted to the waiting queue by a
decode OOM and cannot be prefilled again (no KV).
Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/robustness/test_deactivate_evict_stuck.py
"""
import ast
import logging
import os
import time
import types
import unittest
from typing import Optional

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python", "sglang", "srt", "managers",
                   "scheduler.py")


def _load():
    tree = ast.parse(open(SRC).read())
    fn = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Scheduler" for n in c.body
              if isinstance(n, ast.FunctionDef) and n.name == "_run_to_completion_normal")
    fn.decorator_list = []
    ns = {"os": os, "time": time, "Optional": Optional, "logger": logging.getLogger("t")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), SRC, "exec"), ns)
    return ns["_run_to_completion_normal"]


run_to_completion = _load()


class Fake:
    def __init__(self):
        self.waiting_queue = ["retracted"]
        self.running_batch = None
        self.last_batch = None
        self.evicted = []
        self.calls = 0

    def get_next_batch_to_run(self):
        self.calls += 1
        if self.calls > 1000:
            raise RuntimeError("spinning: the deactivation would never finish")
        return None  # no KV for the retracted request's prefill

    def _evict_all_waiting_requests(self):
        self.evicted += self.waiting_queue
        self.waiting_queue = []


class EvictStuckTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("PRISM_DEACTIVATE_EVICT_STUCK", None)

    def test_stuck_requests_go_back_to_frontend(self):
        f = Fake()
        run_to_completion(f, evict_stuck=True)
        self.assertEqual((f.evicted, f.waiting_queue), (["retracted"], []))

    def test_old_behaviour_spins(self):
        os.environ["PRISM_DEACTIVATE_EVICT_STUCK"] = "0"
        with self.assertRaises(RuntimeError):
            run_to_completion(Fake(), evict_stuck=True)

    def test_without_evict_stuck_nothing_is_evicted(self):
        # outside the deactivation's last step (evict_stuck False), an empty engine just returns
        f = Fake()
        f.waiting_queue = []
        run_to_completion(f)
        self.assertEqual(f.evicted, [])


if __name__ == "__main__":
    unittest.main()
