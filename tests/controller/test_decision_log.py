"""F2.1: the controller's decision log (PRISM_DECISION_LOG) records the state and the actions without changing them.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_decision_log.py
(needs torch for state.py; the rest of SGLang is replaced by stubs, so no GPU and no server).
"""
import json
import os
import sys
import tempfile
import time
import types
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python")
FREE_GB = 20.0


def _load_policy_module():
    """Import simple_global without sglang/__init__ (it pulls outlines, vllm, ...): empty packages, and stubs for
    the two modules the controller only uses for types (io_struct, sglang.utils) and for the GPU memory probe."""
    for name in ["sglang", "sglang.srt", "sglang.multi_model", "sglang.multi_model.scheduling",
                 "sglang.multi_model.scheduling.policy", "sglang.multi_model.scheduling.gpu"]:
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = [os.path.join(ROOT, *name.split("."))]
            sys.modules[name] = m

    class Any(types.ModuleType):
        def __getattr__(self, k):
            if k.startswith("__"):
                raise AttributeError(k)
            return type(k, (), {"__init__": lambda self, *a, **kw: None})

    for name in ["sglang.srt.managers.io_struct", "sglang.utils"]:
        sys.modules.setdefault(name, Any(name))
    utils = types.ModuleType("sglang.srt.utils")
    utils.get_available_gpu_memory = lambda device, gpu_id: FREE_GB
    sys.modules["sglang.srt.utils"] = utils
    import sglang.multi_model.scheduling.policy.simple_global as sg
    from sglang.multi_model.scheduling import model_queue_tracker as mqt
    from sglang.multi_model.scheduling import state as st
    return sg, mqt, st


sg, mqt, st = _load_policy_module()
WEIGHTS = {f"model_{i}": {"model_size": 15.0, "cell_size": 131072} for i in (1, 2, 3)}


def scenario(now):
    """model_1 active and idle for 100 s, model_2 active and busy, model_3 inactive with 3 waiting requests."""
    mem = types.SimpleNamespace(model_weights_memory=15.0, memory_pool_memory=1.0, total_used_memory=16.0,
                                req_to_token_pool_memory=0.0, token_to_kv_pool_memory=1.0)
    insts = {}
    for i, state in ((1, st.ModelState.ACTIVE), (2, st.ModelState.ACTIVE), (3, st.ModelState.INACTIVE)):
        name = f"model_{i}"
        insts[name] = [st.ModelInstanceState(model_name=name, model_path="p", instance_idx=0, gpu_ids=[0],
                                             state=state, memory_usage=mem, init_memory_pool_size=6.0)]
    queues = {name: mqt.ModelQueueTracker(name) for name in insts}
    queues["model_1"]._last_arrival_time = queues["model_1"]._last_finished_time = now - 100
    q2 = queues["model_2"]
    q2.running_reqs.append(mqt.Req(rid="r2", arrival_time=now - 1, slo=1.0, model="model_2", prompt_len=10,
                                   output_len=10, state=mqt.ReqState.RUNNING))
    q2._last_arrival_time = now - 1
    q3 = queues["model_3"]
    for k in range(3):
        q3.waiting_reqs.append(mqt.Req(rid=f"r3{k}", arrival_time=now - 4 + k, slo=1.0, model="model_3",
                                       prompt_len=10, output_len=10))
    q3._last_arrival_time = now - 2
    return queues, insts


def run_policy(log_path):
    if log_path:
        os.environ["PRISM_DECISION_LOG"] = log_path
    else:
        os.environ.pop("PRISM_DECISION_LOG", None)
    os.environ["PRISM_IDLE_THRESHOLD"] = "50"
    policy = sg.SimpleGlobalPolicy(num_gpus=1, gpu_mem=140.0, model_weights_info=WEIGHTS, workers_per_gpu=3)
    now = time.time()
    policy.first_request_time = now - 200
    queues, insts = scenario(now)
    actions = policy.gen_actions(queues, insts)
    return [(type(a).__name__, a.model_name, getattr(a, "preempt", None)) for a in actions]


class DecisionLogTest(unittest.TestCase):
    def test_same_actions_and_one_line_per_cycle(self):
        off = run_policy(None)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "decisions.jsonl")
            on = run_policy(path)
            with open(path) as f:
                lines = f.read().splitlines()
        self.assertEqual(off, on)
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["cycle"], 1)
        self.assertEqual(rec["gpus"]["0"]["free_gb"], FREE_GB)
        self.assertEqual(rec["gpus"]["0"]["available_gb"], FREE_GB)
        m3 = rec["models"]["model_3"]
        self.assertEqual((m3["state"], m3["waiting"]), ("INACTIVE", 3))
        self.assertAlmostEqual(m3["oldest_wait_s"], 4, delta=0.5)
        self.assertAlmostEqual(m3["min_deadline_in_s"], -3, delta=0.5)
        self.assertEqual(rec["models"]["model_2"]["running"], 1)
        logged = sorted((a["kind"], a["model"]) for a in rec["actions"])
        taken = sorted(("activate" if k == "ActivateAction" else "deactivate", m) for k, m, _ in on)
        self.assertEqual(logged, taken)
        self.assertIn(("deactivate", "model_1"), logged)  # idle 100 s > 50 s
        self.assertIn(("activate", "model_3"), logged)  # 15 + 1 GB fit in 20 GB

    def test_off_by_default_writes_nothing(self):
        os.environ.pop("PRISM_DECISION_LOG", None)
        from sglang.multi_model.scheduling.decision_log import DecisionLog
        log = DecisionLog()
        self.assertFalse(log.enabled)
        log.begin(0.0)
        log.action("activate", "m", 0, "x")
        log.end()  # no file, no error


if __name__ == "__main__":
    unittest.main()
