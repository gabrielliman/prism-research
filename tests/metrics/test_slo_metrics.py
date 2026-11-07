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


if __name__ == "__main__":
    unittest.main()
