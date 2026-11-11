"""A request sent back to the frontend by an engine (deactivation, RECOMPUTE) arrives with output_len=512
(srt/managers/scheduler.py _convert_req_to_frontend_reqs); the controller's queue tracker keeps the length the request
first arrived with, which the policies read (_aged_demand, _keep_value, _kv_reserve_gb, _deadline_snapshot).

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_requeue_output_len.py
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_decision_log import mqt  # noqa: E402  (SGLang stubbed out)


def generate_req(output_len, arrival=10.0):
    return types.SimpleNamespace(rid="r1", arrival_time=arrival, slo=5.0, prompt_len=100, output_len=output_len,
                                 is_warmup=False)


class RequeueOutputLenTest(unittest.TestCase):
    def test_requeued_request_keeps_its_output_len(self):
        q = mqt.ModelQueueTracker("m")
        q.enqueue_req(generate_req(128))
        q.enqueue_req(generate_req(512))  # back from a deactivated engine
        self.assertEqual(q.received_reqs["r1"].output_len, 128)
        self.assertAlmostEqual(q.received_reqs["r1"].left_exec_time, 128 * 0.02)

    def test_unknown_length_is_filled_in(self):
        q = mqt.ModelQueueTracker("m")
        q.enqueue_req(generate_req(None))
        q.enqueue_req(generate_req(300))
        self.assertEqual(q.received_reqs["r1"].output_len, 300)


if __name__ == "__main__":
    unittest.main()
