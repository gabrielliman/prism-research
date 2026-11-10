"""F6.16 (D52, D53): A9.4 per-swap preemption, A2.3 predictive residency, A3.1 expected deadline loss, A10.1 value.

Decisions on hand-built states (PLANO_AGENTE.md section 0.6). Units: GB and seconds; an 8B model needs 16 GB and
frees 15.5; swap times as measured in F5.0a for 8B: Ĉ_rot = 6.43 s with preemption, 15.70 s without.
Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/policy/test_f616.py
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_deadline import NOW, NEED, FREES, CAT, snap, _policy, _state, sg, mqt, FREE_GB  # noqa: E402

from sglang.multi_model.scheduling.policy import deadline as dl  # noqa: E402

RP, RNP = 6.43, 15.70


def model(name, gpu=None, waiting=(), running=0, since=None, c_rot=RNP, rate=0.0, slo_typ=None, free_gb=FREES, **kw):
    reqs = [dl.ReqSnap(arrival=w[0], slo=w[1], preempted_at=w[2] if len(w) > 2 else None) for w in waiting]
    return dl.ModelSnap(name=name, gpu=gpu, need_gb=NEED, free_gb=free_gb, waiting=reqs, running=running,
                        active_since=since, c_at=CAT, c_rot=c_rot, c_rot_p=RP, c_rot_np=RNP, rate=rate,
                        slo_typ=slo_typ, **kw)


A94 = dl.Params(cost_aware=True, preempt=False, preempt_per_swap=True, preempt_lambda=3.0, min_residency=10.0)
A92 = dl.Params(cost_aware=True, preempt=False, min_residency=10.0)
A23 = dl.Params(cost_aware=True, preempt=False, predictive=True, min_residency=10.0)
A31 = dl.Params(min_residency=10.0, theta=0.0)


class A94Test(unittest.TestCase):
    def test_idle_victim_is_preempted_for_free(self):
        x = model("x", waiting=[(NOW - 30, 10.0)])
        d = dl.lvf_select(snap([model("idle", 0, since=NOW - 50), x], free=1.0), A94)
        self.assertEqual((d.victims[0][0], d.preempt), ("idle", {"idle": True}))  # lost = 0

    def test_saved_three_times_lost(self):
        # x: 3 requests whose deadline falls between now + 6.43 and now + 15.70 -> saved = 3; victim runs 1 -> lost 1
        x = model("x", waiting=[(NOW - 30, 37.0), (NOW - 30, 38.0), (NOW - 30, 40.0), (NOW - 30, 200.0)])
        v = model("v", 0, running=1, since=NOW - 50)
        d = dl.lvf_select(snap([v, x], free=1.0), A94)
        self.assertEqual(d.preempt, {"v": True})
        self.assertEqual((d.scores["x"]["saved"], d.scores["x"]["lost"]), (3, 1))

    def test_not_enough_saved_no_preemption(self):
        x = model("x", waiting=[(NOW - 30, 37.0), (NOW - 30, 38.0), (NOW - 30, 200.0)])  # saved 2 < 3·1
        v = model("v", 0, running=1, since=NOW - 50)
        d = dl.lvf_select(snap([v, x], free=1.0), A94)
        self.assertEqual(d.preempt, {"v": False})

    def test_without_per_swap_no_flag(self):
        x = model("x", waiting=[(NOW - 30, 37.0)])
        d = dl.lvf_select(snap([model("v", 0, running=1, since=NOW - 50), x], free=1.0), A92)
        self.assertEqual((len(d.victims), d.preempt), (1, {}))


class A23Test(unittest.TestCase):
    def test_popular_idle_model_costs_its_expected_arrival(self):
        # both active and idle now; "pop" gets 0.5 req/s (8 expected during a 15.7 s swap), "rare" none
        pop = model("pop", 0, since=NOW - 100, rate=0.5, slo_typ=7.0)
        rare = model("rare", 0, since=NOW - 50, rate=0.0, slo_typ=7.0)
        x = model("x", waiting=[(NOW - 20, 7.0)])
        s = snap([pop, rare, x], free=1.0)
        self.assertAlmostEqual(dl.eviction_cost(pop, s, A23), RNP - 0.5 * 7.0)
        self.assertEqual(dl.eviction_cost(rare, s, A23), 0.0)
        self.assertEqual(dl.lvf_select(s, A23).victims, [("rare", 0, "lvf rotation for x")])
        # A9.2 does not look at arrivals: both cost 0, the longest active goes
        self.assertEqual(dl.lvf_select(s, A92).victims, [("pop", 0, "lvf rotation for x")])

    def test_below_one_expected_arrival_costs_nothing(self):
        v = model("v", 0, since=NOW - 100, rate=0.05, slo_typ=7.0)  # 0.05 · 15.7 = 0.8 < 1
        self.assertEqual(dl.eviction_cost(v, snap([v]), A23), 0.0)


class A31Test(unittest.TestCase):
    def test_gain_and_loss_counts(self):
        x = model("x", waiting=[(NOW - 2, 30.0), (NOW - 2, 30.0), (NOW - 2, 10.0)])  # viable after 15.7 s: 2
        a = model("a", 0, waiting=[(NOW - 1, 10.0), (NOW - 1, 60.0)], since=NOW - 50)  # misses if away: 1
        s = snap([a, x], free=1.0)
        d = dl.loss_select(s, A31)
        self.assertEqual((d.scores["x"]["gain"], d.scores["a"]["loss"]), (2, 1))
        self.assertEqual(d.victims, [("a", 0, "loss rotation for x")])  # 2 − 1 > 0

    def test_no_swap_when_loss_not_smaller(self):
        x = model("x", waiting=[(NOW - 2, 30.0)])  # gain 1
        a = model("a", 0, waiting=[(NOW - 1, 10.0)], since=NOW - 50)  # loss 1
        d = dl.loss_select(snap([a, x], free=1.0), A31)
        self.assertEqual((d.victims, d.unplaced), ([], ["x"]))

    def test_victim_with_least_loss_per_gb(self):
        x = model("x", waiting=[(NOW - 2, 60.0)] * 5)  # gain 5
        busy = model("busy", 0, waiting=[(NOW - 1, 10.0)] * 2, since=NOW - 300)  # loss 2
        calm = model("calm", 0, waiting=[(NOW - 1, 200.0)], since=NOW - 20)  # loss 0 (still viable after a swap)
        d = dl.loss_select(snap([busy, calm, x], free=1.0), A31)
        self.assertEqual(d.victims, [("calm", 0, "loss rotation for x")])

    def test_lost_queue_does_not_rotate_and_everything_fits(self):
        x = model("x", waiting=[(NOW - 60, 7.0)])  # deadline passed: gain 0
        d = dl.loss_select(snap([model("a", 0, since=NOW - 50), x], free=1.0), A31)
        self.assertEqual(d.victims, [])
        d = dl.loss_select(snap([model("a", 0, since=NOW - 50), x], free=20.0), A31)
        self.assertEqual(d.activations, [("x", 0)])  # contention check: it fits, it is placed

    def test_min_residency_and_budget(self):
        x = model("x", waiting=[(NOW - 2, 60.0)])
        self.assertEqual(dl.loss_select(snap([model("a", 0, since=NOW - 5), x], free=1.0), A31).victims, [])
        self.assertEqual(dl.loss_select(snap([model("a", 0, since=NOW - 50), x], free=1.0, in_flight=1), A31).victims, [])


class WiringTest(unittest.TestCase):
    def tearDown(self):
        sg.get_available_gpu_memory = lambda device, gpu_id: FREE_GB
        for k in list(os.environ):
            if k.startswith("PRISM_"):
                del os.environ[k]

    @staticmethod
    def _acts(policy, slo):
        now = time.time()
        policy.first_request_time = now - 300
        queues, insts = _state(now, slo=slo)
        for i in range(1, 4):
            policy.active_since[f"model_{i}"] = now - 100 * i
        return policy.gen_actions(queues, insts)

    def test_invalid_combinations_fail_loudly(self):
        with self.assertRaises(ValueError):
            _policy("lvf", 2.0, PRISM_LVF_PREEMPT="per_swap")  # needs A9.2
        with self.assertRaises(ValueError):
            _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_LVF_PREEMPT="per_swap", PRISM_SWAP_PREEMPT="1")
        with self.assertRaises(ValueError):
            _policy("edf", 2.0, PRISM_LVF_PREDICTIVE="1")

    def test_a94_per_victim_flag_reaches_the_action(self):
        # model_4 waits 2 s with SLO 15 s: deadline 13 s ahead, inside (6.43, 15.70) -> saved 2 (two requests);
        # victim model_3 runs 1 -> 2 < 3·1 -> no preemption
        p = _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_LVF_PREEMPT="per_swap", PRISM_MIN_RESIDENCY="10")
        de = [a for a in self._acts(p, 15.0) if type(a).__name__ == "DeactivateAction"]
        self.assertEqual([(a.model_name, a.preempt) for a in de], [("model_3", False)])
        p = _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_LVF_PREEMPT="per_swap", PRISM_LVF_PREEMPT_LAMBDA="1",
                    PRISM_MIN_RESIDENCY="10")
        de = [a for a in self._acts(p, 15.0) if type(a).__name__ == "DeactivateAction"]
        self.assertEqual([(a.model_name, a.preempt) for a in de], [("model_3", True)])  # 2 ≥ 1·1

    def test_a31_end_to_end(self):
        # model_4: 2 waiting with SLO 60 (viable after a swap) -> gain 2; actives have nothing waiting -> loss 0
        p = _policy("loss", 2.0, PRISM_MIN_RESIDENCY="10")
        de = [a for a in self._acts(p, 60.0) if type(a).__name__ == "DeactivateAction"]
        self.assertEqual([(a.model_name, a.preempt) for a in de], [("model_3", False)])

    def test_a101_filters_waiting_models_that_cannot_meet_the_deadline(self):
        # SLO 7 s: model_4's requests waited ~1-2 s, deadline < now + 15.7 s -> no viable request -> no swap;
        # with SLO 60 s they are viable and the throughput swap logic decides (idle actives: swap)
        p = _policy("value", 2.0, PRISM_MIN_RESIDENCY="10", PRISM_SWAP_MIN_RESIDENCY="10")
        self.assertEqual([a for a in self._acts(p, 7.0) if type(a).__name__ == "DeactivateAction"], [])
        p = _policy("value", 2.0, PRISM_MIN_RESIDENCY="10", PRISM_SWAP_MIN_RESIDENCY="10")
        self.assertTrue(p._has_viable("model_4", _state(time.time(), slo=60.0)[0]["model_4"], time.time()))

    def test_a23_rate_and_slo_from_the_tracker(self):
        p = _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_LVF_PREDICTIVE="1")
        now = time.time()
        q = mqt.ModelQueueTracker("m")
        for k in range(30):
            q.received_reqs[str(k)] = mqt.Req(rid=str(k), arrival_time=now - 2 * k, slo=7.0)
        self.assertAlmostEqual(p._arrival_rate(q, now), 30 / 60)
        self.assertEqual(p._typical_slo(q), 7.0)


if __name__ == "__main__":
    unittest.main()
