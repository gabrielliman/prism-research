"""D47: the campaign driver's node-wide worker budget (polyaxon/f4_driver.py pick / suite_workers).

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_driver_budget.py
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "polyaxon"))
import f4_driver as d  # noqa: E402

S = {n: os.path.join(ROOT, "polyaxon", "configs", f"f5_camp_{w}_o1_suite.tsv")
     for n, w in ((10, "C1n10"), (14, "C1n14"), (19, "C1n19"), (4, "C4"))}


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.old = d.MAX_WORKERS
        d.MAX_WORKERS = 36

    def tearDown(self):
        d.MAX_WORKERS = self.old

    def test_suite_workers(self):
        for n, path in S.items():
            self.assertEqual(d.suite_workers(path), n)

    def test_head_goes_when_it_fits(self):
        self.assertEqual(d.pick([("a", S[19]), ("b", S[10])], 10), 0)  # 10 + 19 <= 36

    def test_head_waits_and_nothing_overtakes_it(self):
        q = [("big", S[19]), ("mid", S[14]), ("tiny", S[4])]
        self.assertIsNone(d.pick(q, 24))  # 24 + 19 > 36: wait, even though the 4-worker job would fit
        self.assertEqual(d.pick(q, 0), 0)

    def test_off_means_fifo(self):
        d.MAX_WORKERS = 0
        self.assertEqual(d.pick([("a", S[19])], 100), 0)
        self.assertIsNone(d.pick([], 0))


class ExclusiveTest(unittest.TestCase):
    """D48: exclusive suites run alone on the node."""

    def setUp(self):
        self.old = d.EXCLUSIVE, d.MAX_WORKERS
        d.EXCLUSIVE, d.MAX_WORKERS = d.re.compile(r"_C1n1[49]_"), 36

    def tearDown(self):
        d.EXCLUSIVE, d.MAX_WORKERS = self.old

    def test_matches(self):
        self.assertTrue(d.exclusive(S[19]) and d.exclusive(S[14]))
        self.assertFalse(d.exclusive(S[10]) or d.exclusive(S[4]))

    def test_exclusive_head_waits_for_an_empty_node(self):
        q = [("big", S[19]), ("small", S[4])]
        self.assertIsNone(d.pick(q, 4, n_active=1))
        self.assertEqual(d.pick(q, 0, n_active=0), 0)

    def test_nothing_goes_while_an_exclusive_job_runs(self):
        self.assertIsNone(d.pick([("small", S[4])], 19, n_active=1, excl_active=True))

    def test_off_by_default(self):
        d.EXCLUSIVE = None
        self.assertEqual(d.pick([("big", S[19])], 4, n_active=1), 0)


if __name__ == "__main__":
    unittest.main()
