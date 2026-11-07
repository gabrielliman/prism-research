"""polyaxon/slo_metrics.py on hand-built inputs (PLANO_AGENTE.md section 0.6): SLO families and the F5.0 metrics.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/metrics/test_slo_metrics.py
Uses the real registry files (reports/registro/c_rot.json, reports/data/F02/cat/cat_model.json); the expected values
are read from them, so the tests check the rule, not the numbers.
"""
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "polyaxon"))
import slo_metrics as sm  # noqa: E402

L8 = "meta-llama/Llama-3.1-8B-Instruct"
L3 = "meta-llama/Llama-3.2-3B-Instruct"
Q14 = "Qwen/Qwen2.5-14B-Instruct"
Q32 = "Qwen/Qwen2.5-32B-Instruct"
BASE = (0.5, 0.04)  # (TTFT_base, TPOT_base) of the request's model
REQ = {"model": "m_1", "prompt_len": 100}


class ParseTest(unittest.TestCase):
    def test_s6_and_s6p_take_kr_kd(self):
        self.assertEqual(sm.parse_slo("S6:kR=1,kD=5"), ("S6", {"kR": 1.0, "kD": 5.0}))
        self.assertEqual(sm.parse_slo("S6P:kR=2,kD=3"), ("S6P", {"kR": 2.0, "kD": 3.0}))

    def test_wrong_params_rejected(self):
        for bad in ("S6:kA=1,kD=5", "S6P:kR=1", "S6:kR=1,kD=5,kT=2"):
            with self.assertRaises(ValueError):
                sm.parse_slo(bad)

    def test_unknown_family_rejected(self):
        with self.assertRaises(KeyError):
            sm.parse_slo("S7:kR=1,kD=5")


class S6BaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = sm.Refs()
        cls.rot = json.load(open(sm.CROT))

    def test_s6_without_preemption_is_the_finish_median_by_size(self):
        table = self.rot["sem_preempcao"]["por_pesos_gb"]
        for path, key in ((L3, "5.9"), (L8, "15.0"), (Q14, "27.5"), (Q32, "61.0")):
            st, sp = sm.slo_of(REQ, path, "S6", {"kR": 2.0, "kD": 5.0}, self.refs, BASE)
            self.assertAlmostEqual(st, 2.0 * table[key]["c_rot"])
            self.assertAlmostEqual(sp, 5.0 * BASE[1])

    def test_s6p_is_overhead_plus_c_at(self):
        for path in (L3, L8, Q14, Q32):
            st, sp = sm.slo_of(REQ, path, "S6P", {"kR": 1.0, "kD": 3.0}, self.refs, BASE)
            self.assertAlmostEqual(st, self.rot["overhead_s"] + self.refs.c_at(path))
            self.assertAlmostEqual(sp, 3.0 * BASE[1])

    def test_8b_values_of_d39(self):
        """D39: 8B Ĉ_rot p50 15.7 s without preemption, 6.4 s with."""
        self.assertAlmostEqual(self.refs.c_rot(L8, preempt=False), 15.7, delta=0.05)
        self.assertAlmostEqual(self.refs.c_rot(L8, preempt=True), 6.4, delta=0.05)

    def test_without_preemption_is_slower(self):
        for path in (L3, L8, Q14, Q32):
            self.assertGreater(self.refs.c_rot(path, preempt=False), self.refs.c_rot(path, preempt=True))

    def test_size_without_measurement_fails_loudly(self):
        refs = sm.Refs()
        refs.weights = dict(refs.weights, **{"x/40GB": 40.0})
        with self.assertRaises(KeyError):
            refs.c_rot("x/40GB", preempt=False)
        self.assertTrue(math.isfinite(refs.c_rot("x/40GB", preempt=True)))  # S6P only needs Ĉ_at


class ViolationSplitTest(unittest.TestCase):
    """F5.0c: four groups of TTFT misses (PLANO_AGENTE.md section 7)."""
    C = dict(c_at=1.4, c_rot=6.4, cycle=5.0)

    def g(self, inactive, slo, fits):
        return sm.classify_ttft_miss(inactive, slo, fits, **self.C)

    def test_active_or_activating_is_avoidable(self):
        self.assertEqual(self.g(False, 0.1, True), "evit")
        self.assertEqual(self.g(False, 0.1, False), "evit")

    def test_memory_free_uses_activation_cost(self):
        self.assertEqual(self.g(True, 1.0, True), "inev_ativacao")
        self.assertEqual(self.g(True, 1.4, True), "evit_residencia")  # SLO = Ĉ_at: covered, but not with a cycle
        self.assertEqual(self.g(True, 6.3, True), "evit_residencia")
        self.assertEqual(self.g(True, 6.4, True), "evit")

    def test_no_memory_uses_rotation_cost(self):
        self.assertEqual(self.g(True, 1.0, False), "inev_rotacao")
        self.assertEqual(self.g(True, 6.3, False), "inev_rotacao")
        self.assertEqual(self.g(True, 6.4, False), "evit_residencia")
        self.assertEqual(self.g(True, 11.3, False), "evit_residencia")
        self.assertEqual(self.g(True, 11.4, False), "evit")


def ev(t, kind, model="", value=""):
    return {"t": str(t), "source": "x", "kind": kind, "model": model, "value": str(value)}


class EventHelpersTest(unittest.TestCase):
    def test_free_mem_and_cycle(self):
        e = [ev(0.2, "free_mem", value=30), ev(5.2, "free_mem", value=10), ev(10.2, "free_mem", value=20),
             ev(3, "act_req", "m_1")]
        free = sm.free_mem_series(e)
        self.assertAlmostEqual(sm.cycle_of(free), 5.0)
        self.assertEqual(sm.free_at(free, -1), 30.0)   # before the first reading: the first one
        self.assertEqual(sm.free_at(free, 5.2), 10.0)
        self.assertEqual(sm.free_at(free, 9.9), 10.0)
        self.assertEqual(sm.cycle_of(free[:1]), sm.DEFAULT_CYCLE_S)
        self.assertIsNone(sm.free_at([], 1))

    def test_transitions(self):
        e = [ev(1, "act_req", "a"), ev(4, "act_ok", "a"), ev(10, "evict_swap", "b", "a"), ev(12, "deact_ok", "b"),
             ev(20, "evict", "c")]
        spans = sm.transitions(e)
        self.assertEqual(spans, [(1.0, 4.0), (10.0, 12.0), (20.0, math.inf)])
        self.assertTrue(sm.overlaps(spans, 3, 5))
        self.assertFalse(sm.overlaps(spans, 4, 10))
        self.assertTrue(sm.overlaps(spans, 30, 31))


class EvaluateTest(unittest.TestCase):
    """End to end on a two-model level: b inactive with no memory, then a free-memory reading."""

    def test_groups_sum_to_ttft_misses(self):
        refs = sm.Refs()
        cfg = [{"model_name": n, "model_path": L8, "init_placements": [{"on": on}]} for n, on in (("m_1", True), ("m_2", False))]
        e = [ev(0, "free_mem", value=2), ev(5, "free_mem", value=2), ev(10, "free_mem", value=40),
             ev(6, "act_req", "m_2"), ev(30, "act_ok", "m_2")]
        r = lambda i, m, a, ttft, st="ok": {"id": str(i), "model": m, "arrival": a, "prompt_len": 10, "output_len": 10,
                                            "status": st, "ttft": ttft, "tpot": 0.01, "generated": 10,
                                            "latency": ttft + 0.1, "slo_class": "interactive"}
        reqs = [r(0, "m_2", 1.0, 40), r(1, "m_2", 2.0, 40), r(2, "m_1", 3.0, 9.0), r(3, "m_2", 3.5, float("nan"), "unserved")]
        out = sm.evaluate(reqs, e, cfg, "S1:ttft=8,tpot=1", refs)  # 8 s: covers Ĉ_rot (6.4) but not + 5 s cycle
        self.assertEqual(out["viol_ttft_evit_residencia"], 0.75)  # m_2 inactive, no memory (2 GB < 16)
        self.assertEqual(out["viol_ttft_evit"], 0.25)             # m_1 was active
        out = sm.evaluate(reqs, e, cfg, "S1:ttft=5,tpot=1", refs)  # below Ĉ_rot
        self.assertEqual(out["viol_ttft_inev_rotacao"], 0.75)
        groups = ("inev_ativacao", "inev_rotacao", "evit_residencia", "evit")
        self.assertAlmostEqual(sum(out[f"viol_ttft_{g}"] for g in groups), 1 - out["so_ttft"])


class DedFallbackTest(unittest.TestCase):
    """ρ_mem sweep (PRISM_OVL_N > 10): models without a dedicated run take an identical model's pooled base (D44)."""

    def test_extra_model_takes_the_pooled_base_of_its_path(self):
        refs = sm.Refs()
        b1 = refs.base("ovl_mem", "model_1", "p95", L8)
        self.assertIsNotNone(b1)
        self.assertEqual(refs.base("ovl_mem", "model_19", "p95", L8), b1)
        self.assertEqual(sm.bases_for("S2M", "ovl_mem", {"model_14": L8}, refs)["model_14"],
                         refs.base("ovl_mem", "model_1", "p50", L8))

    def test_no_identical_model_no_base(self):
        refs = sm.Refs()
        self.assertIsNone(refs.base("ovl_mem", "model_19"))           # path unknown
        self.assertIsNone(refs.base("ovl_mem", "model_19", "p95", Q32))  # no 32B in C1


if __name__ == "__main__":
    unittest.main()
