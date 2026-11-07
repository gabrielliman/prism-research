"""polyaxon/gpu_idle.py on a hand-built level (F5.0d, PLANO_AGENTE.md section 7).

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/metrics/test_gpu_idle.py
Two 8B-sized models (15 GB each) on a 100 GB GPU, window T = 100 s, grid 0.25 s:
  a: active from the start, one request in the system over [0, 40) and another over [90, +inf) (unserved);
  b: inactive until act_ok at 60 s, one request in the system over [20, 70).
So b has pending demand while inactive over [20, 60) = 40 s, and a is resident with nothing to do over [40, 60) of
that = 20 s · 15 GB = 300 GB·s → 300 / (100 GB · 100 s) = 0.03.
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "polyaxon"))
import gpu_idle as gi  # noqa: E402

CFG = [{"model_name": "a", "model_path": "p", "init_placements": [{"on": True}]},
       {"model_name": "b", "model_path": "p", "init_placements": [{"on": False}]}]


def req(model, arrival, latency):
    return {"model": model, "arrival": arrival, "latency": latency}


def ev(t, kind, model):
    return {"t": str(t), "source": "x", "kind": kind, "model": model, "value": ""}


REQS = [req("a", 0, 40), req("a", 90, math.nan), req("b", 20, 50)]
EV = [ev(15, "act_req", "b"), ev(60, "act_ok", "b")]
GPU = [{"t": str(t), "util": "50" if t < 50 else "100", "total_gb": "100"} for t in range(0, 110)]
W = {"a": 15.0, "b": 15.0}


class IdlenessTest(unittest.TestCase):
    def run_it(self, rho, rho_lat=None):
        return gi.idleness(REQS, EV, CFG, GPU, 100.0, rho, W, 100.0, rho_lat=rho_lat)

    def test_idle_residency_with_pending_demand(self):
        out = self.run_it({"a": 0.1, "b": 0.1})
        self.assertAlmostEqual(out["ocio_residente_demanda"], 0.03, places=6)
        self.assertAlmostEqual(out["frac_tempo_demanda"], 0.40, places=6)

    def test_expected_idleness_follows_the_resident_set(self):
        # a alone over [0, 60): 1 − 0.3; a and b over [60, 100): 1 − min(1, 0.3 + 0.9) = 0
        out = self.run_it({"a": 0.3, "b": 0.9}, rho_lat={"a": 0.1, "b": 0.2})
        self.assertAlmostEqual(out["ocio_esperada"], 0.6 * 0.7, places=6)
        self.assertAlmostEqual(out["ocio_esperada_lat"], 0.6 * 0.9 + 0.4 * 0.7, places=6)
        self.assertAlmostEqual(out["rho_total"], 1.2)

    def test_observed_and_policy_idleness(self):
        out = self.run_it({"a": 0.3, "b": 0.9})
        self.assertAlmostEqual(out["ocio_observada"], 0.25)  # 50 samples at 50%, 50 at 100% inside [0, 100)
        self.assertAlmostEqual(out["ocio_politica"], 0.25 - 0.42, places=6)

    def test_swaps_per_minute(self):
        self.assertAlmostEqual(self.run_it({"a": 0, "b": 0})["trocas_min"], 0.6)  # 1 act_ok in 100 s

    def test_unknown_rho_gives_nan_not_a_number(self):
        out = self.run_it({"a": math.nan, "b": 0.1})
        self.assertTrue(math.isnan(out["ocio_esperada"]))
        self.assertTrue(math.isnan(out["ocio_esperada_lat"]))  # no rho_lat given


if __name__ == "__main__":
    unittest.main()
