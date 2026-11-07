"""F5.0f (D30): the decision log notes a swap reservation that lapsed without the model being activated, once, with
who took the memory (simple_global.py _log_lapsed_reservations). Only logging: the reservations are untouched.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_reservation_lapsed.py
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_decision_log import WEIGHTS, sg  # noqa: E402  (imports the policy with SGLang stubbed out)

NOW = 10_000.0


def policy(log_path):
    if log_path:
        os.environ["PRISM_DECISION_LOG"] = log_path
    else:
        os.environ.pop("PRISM_DECISION_LOG", None)
    p = sg.SimpleGlobalPolicy(num_gpus=1, gpu_mem=140.0, model_weights_info=WEIGHTS, workers_per_gpu=3)
    os.environ.pop("PRISM_DECISION_LOG", None)
    return p


def reserve(p, name, start):
    p.swap_reservation_start[name] = start
    p.swap_reservation_until[name] = start + p.SWAP_RESERVATION


def cycles(p, path, calls):
    """Run _log_lapsed_reservations once per (now, active_models) cycle; the notes of each cycle."""
    for now, active in calls:
        p.dlog.begin(now)
        p._log_lapsed_reservations(now, set(active))
        p.dlog.end()
    with open(path) as f:
        return [[n for n in json.loads(line)["notes"] if n["kind"] == "reservation_lapsed"] for line in f]


class ReservationLapsedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "decisions.jsonl")
        self.p = policy(self.path)
        self.R = self.p.SWAP_RESERVATION
        self.assertGreater(self.R, 0)

    def tearDown(self):
        self.p.dlog._f.close()
        self.tmp.cleanup()

    def test_lapsed_once_with_who_took_the_memory(self):
        start = NOW - self.R - 2.0  # lapsed 2 s ago
        reserve(self.p, "model_3", start)
        self.p.active_since.update({"model_1": start - 50, "model_2": start + 1})  # model_2 activated meanwhile
        self.p.pending_activations[("model_1", 0)] = (16.0, NOW - 1)  # odd but possible: also counts as taking it
        notes = cycles(self.p, self.path, [(NOW, ["model_1", "model_2"]), (NOW + 5, ["model_1", "model_2"])])
        self.assertEqual(len(notes[0]), 1)
        n = notes[0][0]
        self.assertEqual(n["model"], "model_3")
        self.assertAlmostEqual(n["reserved_s"], self.R)
        self.assertAlmostEqual(n["lapsed_ago_s"], 2.0)
        self.assertEqual(n["taken_by"], ["model_2", "model_1"])  # activated since start, then pending ones
        self.assertEqual(notes[1], [])  # logged once
        self.assertIn("model_3", self.p.swap_reservation_until)  # the reservation itself is untouched

    def test_still_running_reservation_is_not_logged(self):
        reserve(self.p, "model_3", NOW - 1.0)
        self.assertEqual(cycles(self.p, self.path, [(NOW, [])]), [[]])

    def test_used_reservation_is_not_logged(self):
        reserve(self.p, "model_3", NOW - self.R - 1)
        reserve(self.p, "model_2", NOW - self.R - 1)
        self.p.pending_activations[("model_2", 0)] = (16.0, NOW - 3)
        # model_3 active, model_2 being activated: both used; and not reported later once they leave
        self.assertEqual(cycles(self.p, self.path, [(NOW, ["model_3"]), (NOW + 5, [])]), [[], []])

    def test_new_reservation_after_a_lapsed_one_is_reported_again(self):
        reserve(self.p, "model_3", NOW - self.R - 1)
        first = cycles(self.p, self.path, [(NOW, [])])
        reserve(self.p, "model_3", NOW + 10)
        later = NOW + 10 + self.R + 1
        notes = cycles(self.p, self.path, [(later, [])])
        self.assertEqual(len(first[0]), 1)
        self.assertEqual(len(notes[-1]), 1)  # a different (model, until): a new lapse

    def test_log_off_no_error(self):
        p = policy(None)
        reserve(p, "model_3", NOW - self.R - 1)
        p.dlog.begin(NOW)
        p._log_lapsed_reservations(NOW, set())
        p.dlog.end()
        self.assertFalse(p.dlog.enabled)


if __name__ == "__main__":
    unittest.main()
