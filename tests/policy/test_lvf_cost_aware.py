"""A9.2 residency-aware lag (lvf_select with Params.cost_aware, PRISM_LVF_COST_AWARE=1; F6, 2026-11-09).

A9.1 scores an active model only by how long it has been active, so it evicted busy models (F6a, H3). A9.2 gives
active and inactive models the same lag measure and weighs the measured swap time Ĉ_rot (c_rot.json): an inactive
model's gain G = its lag when it could start after a swap; an active victim's cost K = the lag its own requests
take if it leaves (0 if it has nothing). Rotation only if G > K + margin; victims cheapest per GB first.
Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/policy/test_lvf_cost_aware.py
Units: GB and seconds; an 8B model needs 16 GB and frees 15.5; Ĉ_rot = 6.43 s (with preemption) unless set.
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_deadline import NOW, NEED, FREES, CAT, snap, _policy, _state, sg, FREE_GB  # noqa: E402

from sglang.multi_model.scheduling.policy import deadline as dl  # noqa: E402
from sglang.multi_model.scheduling import estimators as est  # noqa: E402

ROT = 6.43
CROT = os.path.join(HERE, "..", "..", "reports", "registro", "c_rot.json")


def model(name, gpu=None, waiting=(), running=0, since=None, c_rot=ROT, free_gb=FREES, **kw):
    reqs = [dl.ReqSnap(arrival=w[0], slo=w[1], preempted_at=w[2] if len(w) > 2 else None) for w in waiting]
    return dl.ModelSnap(name=name, gpu=gpu, need_gb=NEED, free_gb=free_gb, waiting=reqs, running=running,
                        active_since=since, c_at=CAT, c_rot=c_rot, **kw)


P = dl.Params(cost_aware=True, preempt=True, budget=1, min_residency=10.0)
P0 = dl.Params(cost_aware=True, preempt=False, budget=1, min_residency=10.0)
A91 = dl.Params(budget=1, min_residency=10.0)


class GainCostTest(unittest.TestCase):
    def test_same_lag_for_active_and_inactive(self):
        # the critique of A9.1: an active model's own late queue counted as −(time active)
        a = model("a", 0, waiting=[(NOW - 8, 2.0)], running=2, since=NOW - 100)
        b = model("b", waiting=[(NOW - 8, 2.0)])
        s = snap([a, b])
        self.assertAlmostEqual(dl.lag_at(a, NOW, P), 7.0)  # 8 − 0.5·2
        self.assertAlmostEqual(dl.lag_at(b, NOW, P), 7.0)
        self.assertAlmostEqual(dl.vlt(a, s, P), -100.0)  # A9.1, unchanged

    def test_gain_counts_the_swap(self):
        b = model("b", waiting=[(NOW - 0.3, 1.0)])  # not late now (0.3 < 0.5), late when it could start
        self.assertAlmostEqual(dl.rotation_gain(b, snap([b]), P), 0.3 + ROT - 0.5)

    def test_cost_of_a_victim(self):
        idle = model("idle", 0, since=NOW - 50)
        runs = model("runs", 0, running=3, since=NOW - 50)
        late = model("late", 0, waiting=[(NOW - 4, 1.0)], running=1, since=NOW - 50)
        s = snap([idle, runs, late])
        self.assertEqual(dl.eviction_cost(idle, s, P), 0.0)
        self.assertEqual(dl.eviction_cost(runs, s, P0), 0.0)  # without preemption its running requests finish
        self.assertAlmostEqual(dl.eviction_cost(runs, s, P), 3 * ROT)  # with preemption they restart: α·Ĉ_rot
        self.assertAlmostEqual(dl.eviction_cost(late, s, P0), 4 + ROT - 0.5)  # its queue waits for it to return


class SelectTest(unittest.TestCase):
    def test_everything_fits_no_rotation(self):
        d = dl.lvf_select(snap([model("a", 0, running=2, since=NOW - 100), model("b", waiting=[(NOW - 5, 1.0)])],
                               free=20.0), P)
        self.assertEqual((d.activations, d.victims), ([("b", 0)], []))

    def test_f6a_case_idle_victim_instead_of_busy_longest(self):
        # A9.1 takes the longest active (busy, late queue); A9.2 the one with nothing to do
        busy = model("busy", 0, waiting=[(NOW - 3, 1.0)], running=4, since=NOW - 400)
        idle = model("idle", 0, since=NOW - 30)
        x = model("x", waiting=[(NOW - 6, 1.0)])
        s = snap([busy, idle, x], free=1.0)
        self.assertEqual(dl.lvf_select(s, A91).victims, [("busy", 0, "lvf rotation for x")])
        self.assertEqual(dl.lvf_select(s, P).victims, [("idle", 0, "lvf rotation for x")])

    def test_no_rotation_when_every_victim_costs_more(self):
        # both active models have later queues than x will have after the swap
        a1 = model("a1", 0, waiting=[(NOW - 20, 1.0)], running=2, since=NOW - 200)
        a2 = model("a2", 0, waiting=[(NOW - 15, 1.0)], running=2, since=NOW - 300)
        x = model("x", waiting=[(NOW - 6, 1.0)])
        d = dl.lvf_select(snap([a1, a2, x], free=1.0), P0)
        self.assertEqual((d.victims, d.unplaced), ([], ["x"]))
        self.assertGreater(d.scores["a1"]["k"], d.scores["x"]["g"])

    def test_late_queue_beats_a_less_late_victim(self):
        a1 = model("a1", 0, waiting=[(NOW - 2, 1.0)], running=1, since=NOW - 200)
        x = model("x", waiting=[(NOW - 30, 1.0)])
        d = dl.lvf_select(snap([a1, x], free=1.0), P0)
        self.assertEqual(d.victims, [("a1", 0, "lvf rotation for x")])

    def test_rotates_before_the_request_is_late(self):
        # A9.1 waits until VLT > 0; A9.2 sees that the request will be late by the time a swap finishes
        idle = model("idle", 0, since=NOW - 50)
        x = model("x", waiting=[(NOW - 0.3, 1.0)])
        self.assertEqual(dl.lvf_select(snap([idle, x], free=1.0), A91).victims, [])
        self.assertEqual(dl.lvf_select(snap([idle, x], free=1.0), P).victims, [("idle", 0, "lvf rotation for x")])

    def test_preempting_a_busy_victim_costs_its_running_requests(self):
        runs = model("runs", 0, running=3, since=NOW - 100)
        x = model("x", waiting=[(NOW - 5, 1.0)])  # G = 5 + 6.43 − 0.5 = 10.9 < 3·6.43 = 19.3
        self.assertEqual(dl.lvf_select(snap([runs, x], free=1.0), P).victims, [])
        self.assertEqual(dl.lvf_select(snap([runs, x], free=1.0), P0).victims, [("runs", 0, "lvf rotation for x")])

    def test_victim_order_cost_per_gb(self):
        # same cost, the one that frees more memory first (GreedyDual-Size); free victims before any of them
        small = model("small", 0, waiting=[(NOW - 2, 1.0)], since=NOW - 100, free_gb=15.5)
        big = model("big", 0, waiting=[(NOW - 2, 1.0)], since=NOW - 50, free_gb=31.0)
        x = model("x", waiting=[(NOW - 40, 1.0)])
        self.assertEqual(dl.lvf_select(snap([small, big, x], free=1.0), P0).victims, [("big", 0, "lvf rotation for x")])
        idle = model("idle", 0, since=NOW - 20)
        self.assertEqual(dl.lvf_select(snap([small, big, idle, x], free=1.0), P0).victims,
                         [("idle", 0, "lvf rotation for x")])

    def test_margin(self):
        a1 = model("a1", 0, waiting=[(NOW - 2, 1.0)], since=NOW - 200)  # K = 2 + 6.43 − 0.5 = 7.93
        x = model("x", waiting=[(NOW - 4, 1.0)])  # G = 4 + 6.43 − 0.5 = 9.93
        self.assertEqual(len(dl.lvf_select(snap([a1, x], free=1.0), P0).victims), 1)
        m = dl.Params(cost_aware=True, preempt=False, min_residency=10.0, margin=3.0)
        self.assertEqual(dl.lvf_select(snap([a1, x], free=1.0), m).victims, [])

    def test_min_residency_budget_cooldown(self):
        young = model("young", 0, since=NOW - 5)
        x = model("x", waiting=[(NOW - 6, 1.0)])
        self.assertEqual(dl.lvf_select(snap([young, x], free=1.0), P).victims, [])
        old = model("old", 0, since=NOW - 50)
        self.assertEqual(dl.lvf_select(snap([old, x], free=1.0, in_flight=1), P).victims, [])
        xc = model("x", waiting=[(NOW - 6, 1.0)], cooldown=True)
        self.assertEqual(dl.lvf_select(snap([old, xc], free=1.0), P).victims, [])

    def test_two_victims_on_budget_one(self):
        i1, i2 = model("i1", 0, since=NOW - 50, free_gb=8.0), model("i2", 0, since=NOW - 60, free_gb=8.0)
        x, y = model("x", waiting=[(NOW - 9, 1.0)]), model("y", waiting=[(NOW - 6, 1.0)])
        d = dl.lvf_select(snap([i1, i2, x, y], free=1.0), P)
        self.assertEqual(sorted(v[0] for v in d.victims), ["i1", "i2"])  # both needed for x; y waits (budget)
        self.assertEqual((d.rotated_for, d.unplaced), (["x"], ["y"]))


class EstimatorTest(unittest.TestCase):
    def test_rotation_cost_interpolation(self):
        t = {5.9: 5.859, 15.0: 6.43, 27.5: 7.215}
        self.assertAlmostEqual(est.rotation_cost(15.0, t), 6.43)
        self.assertAlmostEqual(est.rotation_cost(21.25, t), (6.43 + 7.215) / 2)
        self.assertAlmostEqual(est.rotation_cost(1.0, t), 5.859)
        self.assertAlmostEqual(est.rotation_cost(99.0, t), 7.215)

    def test_table_from_the_measurement(self):
        self.assertAlmostEqual(est.load_rotation_table(CROT, True)[15.0], 6.43)
        self.assertAlmostEqual(est.load_rotation_table(CROT, False)[15.0], 15.698)
        self.assertIsNone(est.load_rotation_table("/nonexistent/c_rot.json", True))


class WiringTest(unittest.TestCase):
    def tearDown(self):
        sg.get_available_gpu_memory = lambda device, gpu_id: FREE_GB
        for k in list(os.environ):
            if k.startswith("PRISM_"):
                del os.environ[k]

    def test_default_lvf_is_a91(self):
        p = _policy("lvf", 2.0)
        self.assertEqual((p.LVF_COST_AWARE, p.CROT_TABLE), (False, None))

    def test_cost_aware_loads_the_table_for_the_preemption_mode(self):
        p = _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_SWAP_PREEMPT="0")
        self.assertAlmostEqual(p.CROT_TABLE[15.0], 15.698)
        p = _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_SWAP_PREEMPT="1")
        self.assertAlmostEqual(p.CROT_TABLE[15.0], 6.43)

    def test_missing_table_fails_loudly(self):
        with self.assertRaises(FileNotFoundError):
            _policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", PRISM_CROT_FILE="/nonexistent/c_rot.json")

    @staticmethod
    def _deacts(policy, slo):
        now = time.time()
        policy.first_request_time = now - 300
        queues, insts = _state(now, slo=slo)
        for i in range(1, 4):
            policy.active_since[f"model_{i}"] = now - 100 * i
        return [a.model_name for a in policy.gen_actions(queues, insts) if type(a).__name__ == "DeactivateAction"]

    def test_busy_actives_end_to_end(self):
        # test_deadline._state with SLO 1 s: model_1..3 active, one running request each; model_4 waiting 2 s.
        # A9.1: VLT = 2 − 0.5 = 1.5 > 0 -> evicts the longest active (model_3), busy.
        # A9.2 with preemption: G = 2 + 6.43 − 0.5 = 7.93 < α·Ĉ_rot = 19.3 (its running request restarts) -> none.
        # A9.2 without preemption: running requests finish, K = 0, G = 2 + 15.7 − 0.5 > 0 -> rotates.
        env = {"PRISM_SWAP_PREEMPT": "1", "PRISM_MIN_RESIDENCY": "10"}
        self.assertEqual(self._deacts(_policy("lvf", 2.0, **env), 1.0), ["model_3"])
        self.assertEqual(self._deacts(_policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", **env), 1.0), [])
        env["PRISM_SWAP_PREEMPT"] = "0"
        self.assertEqual(len(self._deacts(_policy("lvf", 2.0, PRISM_LVF_COST_AWARE="1", **env), 1.0)), 1)


if __name__ == "__main__":
    unittest.main()
