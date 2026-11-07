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


if __name__ == "__main__":
    unittest.main()
