"""F6a.3: decisions of A2.1 (edf_select) and A9.1 (lvf_select) on hand-built states (PLANO_AGENTE.md section 0.6).

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/policy/test_deadline.py
The tests check the decision, not the performance. Units: GB and seconds; an 8B model needs 16 GB (15 + 1).
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

from sglang.multi_model.scheduling.policy import deadline as dl  # noqa: E402

NOW = 1000.0
NEED, FREES, CAT = 16.0, 15.5, 1.4


def model(name, gpu=None, waiting=(), running=0, since=None, **kw):
    """waiting: (arrival, slo) or (arrival, slo, preempted_at)."""
    reqs = [dl.ReqSnap(arrival=w[0], slo=w[1], prompt_len=0, preempted_at=w[2] if len(w) > 2 else None)
            for w in waiting]
    return dl.ModelSnap(name=name, gpu=gpu, need_gb=NEED, free_gb=FREES, waiting=reqs, running=running,
                        active_since=since, c_at=CAT, **kw)


def snap(models, free=0.0, in_flight=0):
    return dl.Snapshot(now=NOW, models={m.name: m for m in models}, gpu_free={0: free}, in_flight=in_flight)


class EdfTest(unittest.TestCase):
    P = dl.Params(floor=0.0, budget=1, min_residency=10.0)

    def test_everything_fits_no_rotation(self):
        s = snap([model("a", 0, since=NOW - 100, running=2), model("b", waiting=[(NOW - 1, 7.0)]),
                  model("c", waiting=[(NOW - 2, 7.0)])], free=40.0)
        d = dl.edf_select(s, self.P)
        self.assertEqual(sorted(d.activations), [("b", 0), ("c", 0)])
        self.assertEqual(d.victims, [])

    def test_memory_exactly_at_the_limit(self):
        d = dl.edf_select(snap([model("b", waiting=[(NOW - 1, 7.0)])], free=NEED), self.P)
        self.assertEqual(d.activations, [("b", 0)])
        d = dl.edf_select(snap([model("b", waiting=[(NOW - 1, 7.0)])], free=NEED - 0.01, ), self.P)
        self.assertEqual(d.activations, [])

    def test_order_by_slack(self):
        # b: deadline in 7 − 1 − 1.4 = 4.6 s; c: 7 − 5 − 1.4 = 0.6 s -> c first; only one fits
        s = snap([model("b", waiting=[(NOW - 1, 7.0)]), model("c", waiting=[(NOW - 5, 7.0)])], free=20.0)
        d = dl.edf_select(s, self.P)
        self.assertEqual(d.activations, [("c", 0)])
        self.assertAlmostEqual(d.scores["c"]["u"], 0.6, places=3)

    def test_lost_queue_does_not_count(self):
        # c's only request is lost (slack 7 − 9 − 1.4 < 0): b (viable) goes first even though c waits longer
        s = snap([model("b", waiting=[(NOW - 1, 7.0)]), model("c", waiting=[(NOW - 9, 7.0)])], free=20.0)
        d = dl.edf_select(s, self.P)
        self.assertEqual(d.activations, [("b", 0)])
        self.assertEqual((d.scores["c"]["u"], d.scores["c"]["viable"], d.scores["c"]["lost"]), (None, 0, 1))

    def test_starvation_c1_rotates_for_viable_model(self):
        # C1: GPU full of busy models; x has a viable request; victim = the one with no viable waiting request
        act = [model("a1", 0, waiting=[(NOW - 0.1, 7.0)], running=3, since=NOW - 200),
               model("a2", 0, running=3, since=NOW - 300),
               model("a3", 0, waiting=[(NOW - 0.2, 7.0)], running=3, since=NOW - 400)]
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "edf rotation for x")])
        self.assertEqual(d.rotated_for, ["x"])
        self.assertEqual(d.activations, [])  # x is activated in a later cycle, once the memory is free

    def test_victim_with_earlier_deadline_is_kept(self):
        # the only active model's own request is more urgent than x's: no rotation
        act = [model("a1", 0, waiting=[(NOW - 6, 7.0)], since=NOW - 200)]
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [])
        self.assertEqual(d.unplaced, ["x"])

    def test_lost_only_model_takes_only_idle_victims(self):
        busy = model("a1", 0, running=2, since=NOW - 200)
        idle = model("a2", 0, since=NOW - 100)
        x = model("x", waiting=[(NOW - 9, 1.0)])  # lost
        d = dl.edf_select(snap([busy, x], free=1.0), self.P)
        self.assertEqual(d.victims, [])
        d = dl.edf_select(snap([busy, idle, x], free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "edf rotation for x")])

    def test_group_swap_c2(self):
        # C2: group A active with no requests, group B waiting (strict SLO, lost): one rotation per cycle
        act = [model(f"a{i}", 0, since=NOW - 150) for i in range(3)]
        wait = [model(f"b{i}", waiting=[(NOW - 3 - i, 0.7)]) for i in range(3)]
        d = dl.edf_select(snap(act + wait, free=1.0), self.P)  # one victim (15.5 GB) + 1 GB free = 16.5 GB
        self.assertEqual(len(d.victims), 1)
        self.assertEqual(d.rotated_for, ["b2"])  # oldest request first among lost queues

    def test_budget_exhausted(self):
        act = [model("a1", 0, running=2, since=NOW - 200)]
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=1.0, in_flight=1), self.P)
        self.assertEqual(d.victims, [])
        self.assertEqual(d.unplaced, ["x"])

    def test_victim_below_min_residency(self):
        act = [model("a1", 0, running=2, since=NOW - 5)]  # resident 5 s < T_min 10 s
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [])

    def test_reserved_model_placed_first(self):
        s = snap([model("b", waiting=[(NOW - 5, 7.0)]), model("x", waiting=[(NOW - 0.1, 7.0)], reserved=True)],
                 free=20.0)
        self.assertEqual(dl.edf_select(s, self.P).activations, [("x", 0)])

    def test_reserved_lost_model_beats_viable_victim(self):
        # F6a triage C1 r2: m3 was evicted for m5 (only lost requests); m3 then gets a fresh viable request. The
        # freed memory must go to m5, not back to m3
        s = snap([model("m3", waiting=[(NOW - 0.5, 7.0)]), model("m5", waiting=[(NOW - 80, 7.0)], reserved=True)],
                 free=20.0)
        self.assertEqual(dl.edf_select(s, self.P).activations, [("m5", 0)])

    def test_two_victims_when_one_is_not_enough(self):
        act = [model("a1", 0, running=1, since=NOW - 200), model("a2", 0, running=1, since=NOW - 300)]
        for a in act:
            a.free_gb = 9.0
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=0.0), self.P)
        self.assertEqual(sorted(v[0] for v in d.victims), ["a1", "a2"])

    def test_impasse_c3_no_victim_frees_enough(self):
        # C3-like: a big model waits, the only candidate victim frees too little: no rotation (A1.1 is the fix, F4)
        act = [model("small", 0, running=1, since=NOW - 200)]
        act[0].free_gb = 6.0
        d = dl.edf_select(snap(act + [model("x", waiting=[(NOW - 1, 7.0)])], free=2.0), self.P)
        self.assertEqual(d.victims, [])


class LvfTest(unittest.TestCase):
    P = dl.Params(alpha=3.0, beta_f=0.5, beta_b=0.0, budget=1, min_residency=10.0)

    def test_everything_fits_no_rotation(self):
        s = snap([model("a", 0, since=NOW - 100, running=2), model("b", waiting=[(NOW - 5, 1.0)])], free=20.0)
        d = dl.lvf_select(s, self.P)
        self.assertEqual((d.activations, d.victims), ([("b", 0)], []))

    def test_vlt_values(self):
        s = snap([model("a", 0, since=NOW - 100), model("b", waiting=[(NOW - 5, 1.0), (NOW - 1, 1.0)])])
        self.assertAlmostEqual(dl.vlt(s.models["a"], s, self.P), -100.0)
        self.assertAlmostEqual(dl.vlt(s.models["b"], s, self.P), 4.5)  # 5 − 0.5·1

    def test_starvation_c1_victim_is_longest_active(self):
        act = [model("a1", 0, running=3, since=NOW - 200), model("a2", 0, running=3, since=NOW - 400),
               model("a3", 0, running=3, since=NOW - 300)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 2, 1.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "lvf rotation for x")])

    def test_rotating_model_with_alpha_beats_waiting(self):
        # r: request preempted 2 s ago -> 3·2 = 6; w: waiting 4 s with SLO 1 -> 3.5. One slot: r first
        r = model("r", waiting=[(NOW - 30, 1.0, NOW - 2)])
        w = model("w", waiting=[(NOW - 4, 1.0)])
        d = dl.lvf_select(snap([r, w], free=20.0), self.P)
        self.assertEqual(d.activations, [("r", 0)])
        self.assertAlmostEqual(d.scores["r"]["vlt"], 6.0)
        d = dl.lvf_select(snap([r, w], free=20.0), dl.Params(alpha=1.0, beta_f=0.5))
        self.assertEqual(d.activations, [("w", 0)])  # α = 1: 2 < 3.5

    def test_not_late_yet_no_rotation(self):
        # waiting 0.3 s with SLO 1: VLT = ReLU(0.3 − 0.5) = 0 -> no rotation
        act = [model("a1", 0, running=3, since=NOW - 200)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 0.3, 1.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [])

    def test_budget_exhausted(self):
        act = [model("a1", 0, running=3, since=NOW - 200)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 5, 1.0)])], free=1.0, in_flight=1), self.P)
        self.assertEqual(d.victims, [])

    def test_victim_below_min_residency(self):
        act = [model("a1", 0, running=3, since=NOW - 9), model("a2", 0, running=3, since=NOW - 50)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 5, 1.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "lvf rotation for x")])
        act[1].active_since = NOW - 8
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 5, 1.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [])

    def test_group_swap_c2_one_rotation_per_budget(self):
        act = [model(f"a{i}", 0, since=NOW - 150 - i) for i in range(3)]
        wait = [model(f"b{i}", waiting=[(NOW - 3 - i, 0.7)]) for i in range(3)]
        d = dl.lvf_select(snap(act + wait, free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "lvf rotation for b2")])
        d = dl.lvf_select(snap(act + wait, free=1.0), dl.Params(budget=2, min_residency=10.0))
        self.assertEqual([v[0] for v in d.victims], ["a2", "a1"])  # b2 then b1, one victim each

    def test_cooldown_blocks_new_rotation(self):
        act = [model("a1", 0, running=3, since=NOW - 200)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 5, 1.0)], cooldown=True)], free=1.0), self.P)
        self.assertEqual(d.victims, [])

    def test_blocked_victim_skipped(self):
        act = [model("a1", 0, since=NOW - 400, blocked=True), model("a2", 0, running=1, since=NOW - 200)]
        d = dl.lvf_select(snap(act + [model("x", waiting=[(NOW - 5, 1.0)])], free=1.0), self.P)
        self.assertEqual(d.victims, [("a2", 0, "lvf rotation for x")])


WEIGHTS = {f"model_{i}": {"model_size": 15.0, "cell_size": 131072} for i in range(1, 5)}


def _policy(eviction, free_gb, **env):
    for k in list(os.environ):
        if k.startswith("PRISM_"):
            del os.environ[k]
    os.environ.update({"PRISM_EVICTION": eviction, "PRISM_IDLE_THRESHOLD": "50", **env})
    sys.modules["sglang.srt.utils"].get_available_gpu_memory = lambda device, gpu_id: free_gb
    sg.get_available_gpu_memory = lambda device, gpu_id: free_gb
    return sg.SimpleGlobalPolicy(num_gpus=1, gpu_mem=140.0, model_weights_info=WEIGHTS, workers_per_gpu=4)


def _state(now, slo=7.0):
    """model_1..3 active and busy (running requests, recent arrivals), model_4 inactive with 2 waiting requests."""
    mem = types.SimpleNamespace(model_weights_memory=15.0, memory_pool_memory=1.0, total_used_memory=16.0,
                                req_to_token_pool_memory=0.0, token_to_kv_pool_memory=1.0)
    insts, queues = {}, {}
    for i in range(1, 5):
        name = f"model_{i}"
        state = st.ModelState.ACTIVE if i <= 3 else st.ModelState.INACTIVE
        insts[name] = [st.ModelInstanceState(model_name=name, model_path="p", instance_idx=0, gpu_ids=[0],
                                             state=state, memory_usage=mem, init_memory_pool_size=6.0)]
        q = queues[name] = mqt.ModelQueueTracker(name)
        q._last_arrival_time = now - 0.5
        if i <= 3:
            q.running_reqs.append(mqt.Req(rid=f"r{i}", arrival_time=now - 0.5, slo=slo, model=name, prompt_len=500,
                                          output_len=300, state=mqt.ReqState.RUNNING))
        else:
            for k in range(2):
                q.waiting_reqs.append(mqt.Req(rid=f"w{k}", arrival_time=now - 2 + k, slo=slo, model=name,
                                              prompt_len=500, output_len=300))
    return queues, insts


def _run(policy, now):
    policy.first_request_time = now - 300
    queues, insts = _state(now)
    for i in range(1, 4):
        policy.active_since[f"model_{i}"] = now - 100 * i
    return policy.gen_actions(queues, insts)


class PolicyWiringTest(unittest.TestCase):
    def tearDown(self):
        sg.get_available_gpu_memory = lambda device, gpu_id: FREE_GB
        for k in list(os.environ):
            if k.startswith("PRISM_"):
                del os.environ[k]

    def test_edf_rotates_without_preemption_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dec.jsonl")
            p = _policy("edf", 2.0, PRISM_MIN_RESIDENCY="10", PRISM_DECISION_LOG=path)
            acts = _run(p, time.time())
            rec = json.loads(open(path).read().splitlines()[0])
        deact = [a for a in acts if type(a).__name__ == "DeactivateAction"]
        self.assertEqual(len(deact), 1)
        self.assertEqual(deact[0].model_name, "model_3")  # all equal urgency (+inf): active longest
        self.assertEqual((deact[0].preempt, deact[0].evict_waiting_requests), (False, True))
        self.assertFalse(hasattr(deact[0], "drain_timeout"))  # D30: no timed drain
        self.assertEqual(rec["policy"]["name"], "edf")
        self.assertEqual(rec["policy"]["rotated_for"], ["model_4"])
        self.assertEqual(rec["policy"]["scores"]["model_4"]["viable"], 2)
        self.assertIn({"kind": "deactivate", "model": "model_3", "gpu": 0, "reason": "edf rotation for model_4",
                       "preempt": False}, rec["actions"])
        self.assertTrue(p.swap_reservation_until["model_4"] > time.time())

    def test_removed_drain_knobs_fail_loudly(self):
        # D30: an old suite that still sets the timed drain must not run a different configuration silently
        for knob in ("PRISM_SWAP_DRAIN", "PRISM_SWAP_DRAIN_TIMEOUT"):
            with self.assertRaises(ValueError):
                _policy("edf", 2.0, **{knob: "1"})
        _policy("edf", 2.0, PRISM_SWAP_DRAIN="0")  # explicitly off is fine

    def test_lvf_activates_when_it_fits(self):
        p = _policy("lvf", 40.0)
        acts = _run(p, time.time())
        self.assertEqual([(type(a).__name__, a.model_name) for a in acts], [("ActivateAction", "model_4")])

    def test_kv_reserve_blocks_activation(self):
        # 16.5 GB free: 15 + 1 fits; with A1.1 b = 8 requests of 800 tokens (8·800·128 KiB = 0.78 GB > 1 GB? no:
        # max(1, 0.78) = 1) it still fits; with b = 16 (1.56 GB) it does not. K_min alone: kvcached's floor, which
        # A1.1 adds since F4, is set to 0 here (tests/policy/test_structural.py covers it)
        now = time.time()
        p = _policy("edf", 16.5, PRISM_KV_RESERVE_REQS="8", PRISM_KV_FLOOR_FRAC="0")
        self.assertEqual([a.model_name for a in _run(p, now) if type(a).__name__ == "ActivateAction"], ["model_4"])
        p = _policy("edf", 16.5, PRISM_KV_RESERVE_REQS="16", PRISM_KV_FLOOR_FRAC="0")
        self.assertEqual([a.model_name for a in _run(p, now) if type(a).__name__ == "ActivateAction"], [])

    def test_default_is_unchanged_idle(self):
        p = _policy("idle", 2.0)
        self.assertEqual((p.EVICTION, p.MIN_RESIDENCY, p.KV_RESERVE_REQS), ("idle", 0.0, 0.0))
        acts = _run(p, time.time())
        self.assertEqual(acts, [])  # nothing idle, nothing fits, no rotation


if __name__ == "__main__":
    unittest.main()
