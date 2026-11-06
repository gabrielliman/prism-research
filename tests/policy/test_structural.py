"""F4.1-F4.3: decisions of the structural constraints A1.1 (KV reserve), A1.2 (impasse detector) and A1.3 (minimum
residency) on hand-built states (PLANO_AGENTE.md sections 0.6 and A1). They check the decision, not performance.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/policy/test_structural.py
Units: GB and seconds. Test GPU: 140 GB, so kvcached's floor (5%) is 7 GB; an 8B model has 15 GB of weights and
128 KiB of KV per token.
"""
import json
import os
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "controller"))
from test_decision_log import FREE_GB, sg, mqt, st  # noqa: E402  (imports the policy with SGLang stubbed out)

from sglang.multi_model.scheduling.policy import structural as s1  # noqa: E402

CELL = 131072
WEIGHTS = {f"model_{i}": {"model_size": 15.0, "cell_size": CELL} for i in range(1, 6)}


# ---------------------------------------------------------------- pure functions


class NeedTest(unittest.TestCase):
    def test_default_rule_is_prism_with_r21(self):
        self.assertEqual(s1.activation_need_gb(15.0, 0.0, 1.0, 0.0, 0.0), 16.0)
        self.assertEqual(s1.activation_need_gb(15.0, 3.0, 1.0, 0.0, 0.0), 19.0)  # A0.3 headroom

    def test_kmin_replaces_activation_kv_when_larger_and_floor_adds(self):
        self.assertEqual(s1.activation_need_gb(15.0, 0.0, 1.0, 0.5, 7.0), 23.0)  # max(1, 0.5) + 7
        self.assertEqual(s1.activation_need_gb(15.0, 0.0, 1.0, 2.5, 7.0), 24.5)

    def test_kmin(self):
        self.assertEqual(s1.kmin_gb(0, [1000], CELL), 0.0)  # off
        self.assertAlmostEqual(s1.kmin_gb(4, [], CELL), 4 * 1024 * CELL / 2**30)  # empty queue: 1024 tokens
        self.assertAlmostEqual(s1.kmin_gb(4, [1000, 2000], CELL), 4 * 1500 * CELL / 2**30)  # 0.73 GB

    def test_residency(self):
        self.assertTrue(s1.resident_long_enough(1.0, 0.0))  # off
        self.assertTrue(s1.resident_long_enough(None, 10.0))  # not seen active yet
        self.assertFalse(s1.resident_long_enough(9.99, 10.0))
        self.assertTrue(s1.resident_long_enough(10.0, 10.0))  # exactly at the limit


class DetectorTest(unittest.TestCase):
    def x(self, now, served=100.0, waiting=2, transitions=0):
        return s1.StallInput(now=now, served_total=served, active_with_waiting=waiting, transitions=transitions)

    def test_stall_accumulates_and_fires_at_delta(self):
        d = s1.DeadlockDetector(30.0)
        self.assertEqual(d.update(self.x(0.0)), 0.0)
        self.assertEqual(d.update(self.x(25.0)), 25.0)
        self.assertFalse(d.fired(25.0))
        self.assertEqual(d.update(self.x(30.0)), 30.0)
        self.assertTrue(d.fired(30.0))  # exactly Δ

    def test_any_token_resets(self):
        d = s1.DeadlockDetector(30.0)
        d.update(self.x(0.0))
        d.update(self.x(20.0))
        self.assertEqual(d.update(self.x(25.0, served=101.0)), 0.0)  # one token served
        self.assertEqual(d.update(self.x(50.0, served=101.0)), 25.0)  # the clock restarts at 25

    def test_no_active_work_or_transition_resets(self):
        d = s1.DeadlockDetector(30.0)
        d.update(self.x(0.0))
        self.assertEqual(d.update(self.x(20.0, waiting=0)), 0.0)  # every active model idle: not an impasse
        d.update(self.x(21.0))
        self.assertEqual(d.update(self.x(40.0, transitions=1)), 0.0)  # activation/deactivation in flight
        self.assertEqual(d.update(self.x(45.0)), 0.0)
        self.assertEqual(d.update(self.x(60.0)), 15.0)

    def test_disabled_never_fires_and_reset(self):
        d = s1.DeadlockDetector(0.0)
        d.update(self.x(0.0))
        self.assertFalse(d.fired(d.update(self.x(1e6))))
        d = s1.DeadlockDetector(30.0)
        d.update(self.x(0.0))
        d.update(self.x(31.0))
        d.reset(31.0)
        self.assertEqual(d.update(self.x(40.0)), 0.0)


class VictimTest(unittest.TestCase):
    def c(self, name, value, active_for, excluded=False):
        return s1.VictimCand(name=name, gpu=0, value_per_gb=value, active_for_s=active_for, excluded=excluded)

    def test_least_value_per_gb(self):
        v = s1.deadlock_victim([self.c("a", 5.0, 100), self.c("b", 1.0, 100), self.c("c", 3.0, 100)], 10.0)
        self.assertEqual(v.name, "b")

    def test_min_residency_and_exclusion(self):
        cands = [self.c("a", 5.0, 100), self.c("b", 1.0, 5), self.c("c", 3.0, 100, excluded=True)]
        self.assertEqual(s1.deadlock_victim(cands, 10.0).name, "a")  # b too recent, c already leaving
        self.assertEqual(s1.deadlock_victim(cands, 0.0).name, "b")
        self.assertIsNone(s1.deadlock_victim([self.c("b", 1.0, 5)], 10.0))  # nobody may leave
        self.assertIsNone(s1.deadlock_victim([], 10.0))

    def test_tie_goes_to_longest_resident(self):
        v = s1.deadlock_victim([self.c("a", 0.0, 100), self.c("b", 0.0, 300)], 10.0)
        self.assertEqual(v.name, "b")


# ---------------------------------------------------------------- wired into SimpleGlobalPolicy


def _policy(eviction, free_gb, **env):
    for k in list(os.environ):
        if k.startswith("PRISM_"):
            del os.environ[k]
    os.environ.update({"PRISM_EVICTION": eviction, "PRISM_IDLE_THRESHOLD": "50", **env})
    sys.modules["sglang.srt.utils"].get_available_gpu_memory = lambda device, gpu_id: free_gb
    sg.get_available_gpu_memory = lambda device, gpu_id: free_gb
    return sg.SimpleGlobalPolicy(num_gpus=1, gpu_mem=140.0, model_weights_info=WEIGHTS, workers_per_gpu=8)


def _impasse(now, waiting=None, n_active=3, inactive_waiting=2, running=None, last_arrival_ago=0.5):
    """The T1 signature (F1.1, F3 anomaly 1): model_1..n_active resident, each with requests waiting and none
    running (no KV page for any prefill); model_{n_active+1} inactive with requests; no token served."""
    waiting = waiting or {i: 3 for i in range(1, n_active + 1)}
    running = running or {}
    mem = types.SimpleNamespace(model_weights_memory=15.0, memory_pool_memory=1.0, total_used_memory=16.0,
                                req_to_token_pool_memory=0.0, token_to_kv_pool_memory=1.0)
    insts, queues = {}, {}
    for i in range(1, n_active + 2):
        name = f"model_{i}"
        state = st.ModelState.ACTIVE if i <= n_active else st.ModelState.INACTIVE
        insts[name] = [st.ModelInstanceState(model_name=name, model_path="p", instance_idx=0, gpu_ids=[0],
                                             state=state, memory_usage=mem, init_memory_pool_size=6.0)]
        q = queues[name] = mqt.ModelQueueTracker(name)
        q._last_arrival_time = now - last_arrival_ago
        q.served_tokens = 5000 * i
        n = waiting.get(i, 0) if i <= n_active else inactive_waiting
        for k in range(n):
            q.waiting_reqs.append(mqt.Req(rid=f"{name}-w{k}", arrival_time=now - 60 + k + i, slo=7.0, model=name,
                                          prompt_len=1000, output_len=250))
        for k in range(running.get(i, 0)):
            q.running_reqs.append(mqt.Req(rid=f"{name}-r{k}", arrival_time=now - 60, slo=7.0, model=name,
                                          prompt_len=1000, output_len=250, state=mqt.ReqState.RUNNING))
    return queues, insts


def _cycle(p, now, active_for=(300, 200, 100), **kw):
    p.first_request_time = now - 600
    queues, insts = _impasse(now, **kw)
    for i, a in enumerate(active_for, start=1):
        p.active_since[f"model_{i}"] = now - a
    return p.gen_actions(queues, insts), queues


def _deact(acts):
    return [(a.model_name, a.preempt) for a in acts if type(a).__name__ == "DeactivateAction"]


def _act(acts):
    return [a.model_name for a in acts if type(a).__name__ == "ActivateAction"]


class _Env(unittest.TestCase):
    def tearDown(self):
        sg.get_available_gpu_memory = lambda device, gpu_id: FREE_GB
        for k in list(os.environ):
            if k.startswith("PRISM_"):
                del os.environ[k]


class KvReserveWiringTest(_Env):
    """A1.1 in the activation step of every strategy (A0.1 idle, A0.3 throughput, F6a edf/lvf)."""

    def test_default_activates_into_kvcached_floor(self):
        # 17 GB free: Prism + R2.1 activates (15 + 1), leaving 1 GB, below the 7 GB kvcached keeps out of the KV pool
        # (the 14-model T1 of F1.1)
        acts, _ = _cycle(_policy("idle", 17.0), time.time())
        self.assertEqual(_act(acts), ["model_4"])

    def test_a11_blocks_it_in_idle_and_throughput(self):
        for ev in ("idle", "throughput", "edf"):
            p = _policy(ev, 17.0, PRISM_KV_RESERVE_REQS="4")
            self.assertAlmostEqual(p.KV_FLOOR_GB, 7.0)
            acts, _ = _cycle(p, time.time())
            self.assertEqual(_act(acts), [], ev)

    def test_memory_exactly_at_the_limit(self):
        # need = 15 + max(1, 4 · 1250 · 128 KiB = 0.61 GB) + 7 = 23 GB
        p = _policy("idle", 23.0, PRISM_KV_RESERVE_REQS="4")
        self.assertAlmostEqual(p._activation_need_gb("model_4", None) , 15 + max(1.0, 4 * 1024 * CELL / 2**30) + 7)
        acts, _ = _cycle(p, time.time())
        self.assertEqual(_act(acts), ["model_4"])
        acts, _ = _cycle(_policy("idle", 22.99, PRISM_KV_RESERVE_REQS="4"), time.time())
        self.assertEqual(_act(acts), [])

    def test_kmin_counts_when_larger(self):
        # b = 16: 16 · 1250 tokens · 128 KiB = 2.44 GB > 1 GB -> need 15 + 2.44 + 7
        p = _policy("idle", 30.0, PRISM_KV_RESERVE_REQS="16")
        q, _ = _impasse(time.time())
        self.assertAlmostEqual(p._activation_need_gb("model_4", q["model_4"]), 15 + 16 * 1250 * CELL / 2**30 + 7)

    def test_default_and_floor_off(self):
        p = _policy("idle", 17.0)
        self.assertEqual((p.KV_RESERVE_REQS, p.KV_FLOOR_GB, p.DEADLOCK_S, p.MIN_RESIDENCY), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(p._activation_need_gb("model_4", None), 16.0)


class DetectorWiringTest(_Env):
    """A1.2 on the T1 state: GPU full, every resident model with a queue, no token for Δ_imp."""

    def _stall(self, p, now, shift=31.0, **kw):
        _cycle(p, now, **kw)  # first cycle: starts the clock (unless something resets it)
        if p.deadlock.since is not None:
            p.deadlock.since -= shift
        return _cycle(p, now, **kw)

    def test_fires_on_the_impasse_and_logs_the_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dec.jsonl")
            # model_2 has the least queued work per GB: it leaves; preempted (its requests cannot progress)
            p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30", PRISM_DECISION_LOG=path)
            acts, _ = self._stall(p, time.time(), waiting={1: 5, 2: 1, 3: 3})
            recs = [json.loads(line) for line in open(path)]
        self.assertEqual(_deact(acts), [("model_2", True)])
        note = [n for n in recs[-1]["notes"] if n["kind"] == "deadlock"][0]
        self.assertEqual(note["model"], "model_2")
        self.assertGreaterEqual(note["stalled_s"], 30.0)
        self.assertEqual(note["unblocks"], "model_1")  # oldest waiting request
        self.assertEqual(sorted(note["candidates"]), ["model_1", "model_2", "model_3"])
        self.assertIn({"kind": "deactivate", "model": "model_2", "gpu": 0, "reason": "deadlock break for model_1",
                       "preempt": True}, recs[-1]["actions"])
        self.assertIsNone(p.deadlock.since)  # next eviction only after another Δ_imp

    def test_not_before_delta(self):
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30")
        acts, _ = self._stall(p, time.time(), shift=20.0)
        self.assertEqual(_deact(acts), [])

    def test_not_while_tokens_flow(self):
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30")
        now = time.time()
        _cycle(p, now)
        p.deadlock.since -= 31
        p.deadlock.last_served -= 1  # one token served since the last cycle
        acts, _ = _cycle(p, now)
        self.assertEqual(_deact(acts), [])

    def test_not_with_an_activation_in_flight(self):
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30")
        p.pending_activations[("model_5", 0)] = (16.0, time.time())
        acts, _ = self._stall(p, time.time())
        self.assertEqual(_deact(acts), [])

    def test_not_when_resident_models_are_idle(self):
        # nothing waits at a resident model (only the inactive one): that is the idle threshold's case, not an impasse
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30")
        acts, _ = self._stall(p, time.time(), waiting={1: 0, 2: 0, 3: 0}, last_arrival_ago=5.0)
        self.assertEqual(_deact(acts), [])

    def test_min_residency_protects_recent_models(self):
        # model_2 is the least valuable but was activated 5 s ago: with T_min = 10 s model_3 (next least) leaves
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30", PRISM_MIN_RESIDENCY="10")
        acts, _ = self._stall(p, time.time(), waiting={1: 5, 2: 1, 3: 3}, active_for=(300, 5, 100))
        self.assertEqual(_deact(acts), [("model_3", True)])
        # all recent: nobody leaves, and the clock keeps running for the next cycle
        p = _policy("idle", 6.6, PRISM_DEADLOCK_S="30", PRISM_MIN_RESIDENCY="10")
        acts, _ = self._stall(p, time.time(), active_for=(5, 5, 5))
        self.assertEqual(_deact(acts), [])
        self.assertIsNotNone(p.deadlock.since)

    def test_works_with_the_throughput_swap(self):
        # with no inactive model waiting the swap has nothing to do, and the detector acts on A0.3's criterion
        p = _policy("throughput", 6.6, PRISM_DEADLOCK_S="30", PRISM_ACTIVATION_HEADROOM_GB="3")
        acts, _ = self._stall(p, time.time(), waiting={1: 5, 2: 1, 3: 3}, inactive_waiting=0)
        self.assertEqual(_deact(acts), [("model_2", True)])

    def test_a_swap_in_the_same_cycle_is_a_transition(self):
        # stalled for 60 s, but this cycle the throughput swap evicts for model_4 (large backlog): the detector
        # waits for the swap's effect instead of evicting a second model
        now = time.time()
        p = _policy("throughput", 6.6, PRISM_DEADLOCK_S="30", PRISM_ACTIVATION_HEADROOM_GB="3",
                    PRISM_SWAP_MIN_RESIDENCY="0")
        p.deadlock.since, p.deadlock.last_served = now - 60, 5000.0 * (1 + 2 + 3 + 4)  # = _impasse's served total
        acts, _ = _cycle(p, now, waiting={1: 5, 2: 1, 3: 3}, inactive_waiting=40)
        self.assertEqual(_deact(acts), [("model_2", False)])  # the swap's own eviction (no preemption, A0.3)
        self.assertIsNone(p.deadlock.since)

    def test_off_by_default(self):
        p = _policy("idle", 6.6)
        acts, _ = self._stall(p, time.time(), shift=1e5)
        self.assertEqual(_deact(acts), [])


class MinResidencyWiringTest(_Env):
    """A1.3 on the eviction paths that had no minimum residency (idle; pressure and fair)."""

    def _idle_state(self, p, now, active_for):
        # model_1 resident, nothing queued, last request 300 s ago: idle for the 50 s threshold
        p.first_request_time = now - 600
        queues, insts = _impasse(now, waiting={1: 0}, n_active=1, inactive_waiting=0, last_arrival_ago=300)
        p.active_since["model_1"] = now - active_for
        return p.gen_actions(queues, insts)

    def test_idle_eviction_waits_for_t_min(self):
        now = time.time()
        self.assertEqual(_deact(self._idle_state(_policy("idle", 60.0), now, 3)), [("model_1", False)])
        p = _policy("idle", 60.0, PRISM_MIN_RESIDENCY="10")
        self.assertEqual(_deact(self._idle_state(p, now, 3)), [])
        self.assertEqual(_deact(self._idle_state(p, now, 12)), [("model_1", False)])

    def test_pressure_respects_t_min(self):
        now = time.time()
        p = _policy("pressure", 1.0, PRISM_MIN_RESIDENCY="10")
        p.first_request_time = now - 600
        queues, insts = _impasse(now, waiting={1: 0, 2: 0, 3: 0}, last_arrival_ago=5.0)
        for i, a in enumerate((300, 3, 4), start=1):
            p.active_since[f"model_{i}"] = now - a
        self.assertEqual(_deact(p.gen_actions(queues, insts)), [("model_1", False)])  # the only one old enough


if __name__ == "__main__":
    unittest.main()
