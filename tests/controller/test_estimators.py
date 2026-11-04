"""F2.3–F2.5 estimators (python/sglang/multi_model/scheduling/estimators.py) on hand-built inputs.

Run: python3 -m unittest tests/controller/test_estimators.py
"""
import importlib.util
import os
import random
import unittest

spec = importlib.util.spec_from_file_location("estimators", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "python", "sglang", "multi_model", "scheduling", "estimators.py"))
est = importlib.util.module_from_spec(spec)
spec.loader.exec_module(est)

CAT = {"a": 0.5, "b": 0.06, "c": 1.1}
PRE = {"prefill_a": 0.02, "prefill_b": 0.0001}


class EstimatorTest(unittest.TestCase):
    def test_activation_cost(self):
        self.assertAlmostEqual(est.activation_cost(15.0, 0, CAT), 0.5 + 0.9)
        self.assertAlmostEqual(est.activation_cost(15.0, 2, CAT), 0.5 + 0.9 + 2.2)

    def test_queue_time_packs_batches(self):
        self.assertEqual(est.queue_time([], PRE), 0.0)
        # 3 × 3000 tokens with an 8192-token budget: two batches (6000, 3000)
        self.assertAlmostEqual(est.queue_time([3000] * 3, PRE), (0.02 + 0.6) + (0.02 + 0.3))
        # one prompt larger than the budget is still one batch
        self.assertAlmostEqual(est.queue_time([10000], PRE), 0.02 + 1.0)

    def test_queue_time_hybrid(self):
        # few recent completions: prefill sum of 2 × 1000 ahead (one batch) + own 500
        self.assertAlmostEqual(est.queue_time_hybrid([1000, 1000], 500, PRE, 3),
                               (0.02 + 0.2) + (0.02 + 0.05))
        # 15 first tokens in 30 s (0.5/s): 2 ahead + itself = 6 s
        self.assertAlmostEqual(est.queue_time_hybrid([1000, 1000], 500, PRE, 15), 6.0)

    def test_rate_converges_on_poisson(self):
        rng = random.Random(1)
        e = est.RateEstimator(10, 60, 2, start=0.0)
        t = 0.0
        while t < 600:
            t += rng.expovariate(0.5)
            e.arrival(t)
        self.assertAlmostEqual(e.rates(600)[1], 0.5, delta=0.15)

    def test_unbiased_early(self):
        e = est.RateEstimator(10, 60, 2, start=0.0)
        for k in range(1, 6):  # 1 req/s for the first 5 s
            e.arrival(float(k))
        self.assertAlmostEqual(e.rates(5.0)[1], 1.0, delta=0.15)

    def test_burst_and_lull_switch_to_short_window(self):
        e = est.RateEstimator(10, 60, 2, start=0.0)
        for k in range(120):  # 0.5 req/s for 240 s
            e.arrival(2.0 * k)
        self.assertAlmostEqual(e.rate(240), e.rates(240)[1])  # steady: long window
        for k in range(30):  # burst: 5 req/s for 6 s
            e.arrival(240 + 0.2 * k)
        short, long_ = e.rates(246)
        self.assertGreater(short, 2 * long_)
        self.assertEqual(e.rate(246), short)
        # lull: nothing for 60 s; the short window drops first
        short, long_ = e.rates(306)
        self.assertLess(short * 2, long_)
        self.assertEqual(e.rate(306), short)
        self.assertEqual(est.RateEstimator(10, 60, 2, start=0.0, symmetric=False).rate(0.0), 0.0)

    def test_expected_arrivals(self):
        e = est.RateEstimator(10, 60, 2, start=0.0)
        for k in range(600):
            e.arrival(float(k))
        self.assertAlmostEqual(e.expected_arrivals(600, 15), 15, delta=1.5)


if __name__ == "__main__":
    unittest.main()
