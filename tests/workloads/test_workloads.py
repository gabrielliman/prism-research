"""F3.1/F3.2-F3.5: the workload generators produce what their specification says (polyaxon/workloads.py).

Long horizons, so the checks are on the process, not on the sampling noise of one short level (the realized
statistics of each catalogue level are in reports/registro/cargas.md). CPU only:
  /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/workloads/test_workloads.py
"""
import argparse
import os
import statistics
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "polyaxon"))
import workloads as w  # noqa: E402


def args(**kw):
    p = argparse.ArgumentParser()
    w.add_args(p)
    a = p.parse_args(["--models", *[f"model_{i}" for i in range(1, kw.pop("n", 10) + 1)]])
    a.time_scale = 1.0
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def gaps_cv(ts):
    g = np.diff(np.sort(ts))
    return g.std() / g.mean()


class Processes(unittest.TestCase):
    def test_renewal_constant_rate_and_cv(self):
        rng = np.random.default_rng(1)
        for cv in (1.0, 2.0):
            ts = w.renewal_on_intensity(rng, *w.cumulative(lambda t: np.full_like(t, 0.5), 40000), cv)
            self.assertAlmostEqual(len(ts) / 40000, 0.5, delta=0.5 * 0.03)
            self.assertAlmostEqual(gaps_cv(ts), cv, delta=cv * 0.05)

    def test_ipp_rate_and_cv_formula(self):
        rng = np.random.default_rng(2)
        rate, on, off = 0.2, 20.0, 40.0
        ts = w.ipp_times(rng, rate, on, off, 400000)
        self.assertAlmostEqual(len(ts) / 400000, rate, delta=rate * 0.03)
        self.assertAlmostEqual(gaps_cv(ts), w.ipp_cv(rate, on, off), delta=w.ipp_cv(rate, on, off) * 0.05)
        self.assertTrue(2 <= w.ipp_cv(rate, on, off) <= 4)  # C7 default inside the plan's CV 2-4

    def test_zipf_shares(self):
        s = w.zipf_shares(4, 1.0)
        self.assertAlmostEqual(s.sum(), 1)
        self.assertAlmostEqual(s[0] / s[1], 2)
        np.testing.assert_allclose(w.zipf_shares(3, 0.0), [1 / 3] * 3)

    def test_drift_rotation(self):
        o = w.drift_orders(4, 10, 40)
        self.assertEqual(o[0], [0, 1, 2, 3])
        self.assertEqual(o[1], [1, 0, 2, 3])
        self.assertEqual(o[3], [1, 2, 3, 0])  # after n-1 swaps the top model is last, the others rose one rank
        for a, b in zip(o, o[1:]):  # one adjacent swap per period: gradual
            self.assertEqual(sum(x != y for x, y in zip(a, b)), 2)


class Patterns(unittest.TestCase):
    def test_zipf_drift_total_rate_and_rotation(self):
        a = args(n=6, pattern="zipf_drift", total_rate=2.0, duration=50 * 300, drift_period=300, zipf_alpha=1.0)
        reqs, _ = w.build(a)
        self.assertAlmostEqual(len(reqs) / a.duration, 2.0, delta=2.0 * 0.03)
        first = [r for r in reqs if r[0] < 300]
        top = max(set(r[1] for r in first), key=lambda m: sum(r[1] == m for r in first))
        self.assertEqual(top, "model_1")  # rank 1 at the start
        p5 = [r for r in reqs if 5 * 300 <= r[0] < 6 * 300]  # after 5 = n-1 swaps model_1 is last
        cnt = {m: sum(r[1] == m for r in p5) for m in a.models}
        self.assertEqual(min(cnt, key=cnt.get), "model_1")

    def test_diurnal_mean_and_swing(self):
        a = args(n=4, pattern="diurnal", total_rate=2.0, duration=20 * 1200, diurnal_amp=0.8, diurnal_period=1200,
                 zipf_alpha=0.0)
        reqs, _ = w.build(a)
        t = np.array([r[0] for r in reqs])
        self.assertAlmostEqual(len(t) / a.duration, 2.0, delta=0.06)
        phase = t % 1200
        trough = ((phase < 100) | (phase > 1100)).sum() / 200
        peak = ((phase > 500) & (phase < 700)).sum() / 200
        self.assertGreater(peak / trough, 5)  # (1+A)/(1-A) = 9 at the extremes, averaged over +-100 s

    def test_bursty_target_cv_in_info(self):
        a = args(n=3, pattern="bursty", rate=0.2, duration=100000, burst_on=20, burst_off=40)
        reqs, info = w.build(a)
        self.assertAlmostEqual(info["target_cv"], w.ipp_cv(0.2, 20, 40))
        cvs = [gaps_cv([r[0] for r in reqs if r[1] == m]) for m in a.models]
        self.assertAlmostEqual(statistics.median(cvs), info["target_cv"], delta=info["target_cv"] * 0.1)

    def test_classes_do_not_move_arrivals(self):
        a0 = args(n=5, pattern="zipf_drift", total_rate=1.0, duration=600)
        a1 = args(n=5, pattern="zipf_drift", total_rate=1.0, duration=600, batch_frac=0.3)
        r0, _ = w.build(a0)
        r1, _ = w.build(a1)
        self.assertEqual([r[:4] for r in r0], [r[:4] for r in r1])
        a2 = args(n=5, pattern="zipf_drift", total_rate=1.0, duration=60000, batch_frac=0.3)
        r2, _ = w.build(a2)
        self.assertAlmostEqual(sum(r[4] == "batch" for r in r2) / len(r2), 0.3, delta=0.01)

    def test_same_seed_same_workload(self):
        a = args(n=4, pattern="bursty", rate=0.3, duration=600)
        self.assertEqual(w.build(a)[0], w.build(args(n=4, pattern="bursty", rate=0.3, duration=600))[0])
        self.assertNotEqual(w.build(a)[0], w.build(args(n=4, pattern="bursty", rate=0.3, duration=600, seed=7))[0])


class Traces(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        rng = np.random.default_rng(3)
        rows = []
        for e, rate in (("a", 1.0), ("b", 0.5), ("c", 0.25), ("d", 0.1)):
            for t in w.renewal_on_intensity(rng, *w.cumulative(lambda x, r=rate: np.full_like(x, r), 2000), 2.0):
                rows.append((t, e, int(rng.integers(10, 5000)), int(rng.integers(1, 3000))))
        rows.sort()
        self.path = os.path.join(self.dir, "t.csv.gz")
        w.write_trace(self.path, rows, {"source": "test"})
        self.rows = rows

    def test_rank_mapping_scale_and_cap(self):
        a = args(n=3, pattern="trace", trace=self.path, time_scale=0.5, max_prompt=4096, max_output=2048)
        reqs, info = w.build(a)
        self.assertEqual({r[1] for r in reqs}, {"model_1", "model_2", "model_3"})  # entity d (least) left out
        n1 = sum(r[1] == "model_1" for r in reqs)
        self.assertEqual(n1, sum(r[1] == "a" for r in self.rows))  # most frequent entity -> model_1
        self.assertAlmostEqual(a.duration, max(r[0] for r in self.rows) * 0.5, places=2)  # trace stores ms
        self.assertLessEqual(max(r[2] for r in reqs), 4096)
        self.assertGreater(info["capped_frac"]["prompt"], 0)
        # time scaling keeps the CV of each entity (section 5.3, item 6)
        before = gaps_cv([r[0] for r in self.rows if r[1] == "a"])
        after = gaps_cv([r[0] for r in reqs if r[1] == "model_1"])
        self.assertAlmostEqual(before, after, places=2)

    def test_empirical_lengths_drawn_from_table(self):
        a = args(n=2, pattern="constant", rate=1.0, duration=500, lengths="empirical:" + self.path)
        reqs, _ = w.build(a)
        pairs = {(p, o) for _, _, p, o in self.rows}
        self.assertTrue(all((r[2], r[3]) in pairs for r in reqs))


if __name__ == "__main__":
    unittest.main()
