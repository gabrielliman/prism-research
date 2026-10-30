"""P12: the engines tell a dead model service from a live one by the PID it records (memory_arbiter.py).

Run: python3 -m unittest tests/robustness/test_model_service_alive.py
"""
import importlib.util
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import torch  # noqa: F401
except ImportError:  # memory_arbiter only needs torch for the arbiter itself, not for the PID helpers
    import types

    sys.modules["torch"] = types.ModuleType("torch")
spec = importlib.util.spec_from_file_location(
    "memory_arbiter", os.path.join(HERE, "..", "..", "python", "sglang", "multi_model", "memory_arbiter.py")
)
memory_arbiter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory_arbiter)

SERVICE_ID = 97  # not used by a real server


class ModelServiceAliveTest(unittest.TestCase):
    def setUp(self):
        self.old_user = os.environ.get("USER")
        os.environ["USER"] = f"p12test{os.getpid()}"
        self.path = memory_arbiter._model_service_pid_path(SERVICE_ID)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        if self.old_user is None:
            del os.environ["USER"]
        else:
            os.environ["USER"] = self.old_user

    def _register(self, pid):
        with open(self.path, "w") as f:
            f.write(str(pid))

    def test_not_registered(self):
        self.assertIsNone(memory_arbiter.model_service_alive(SERVICE_ID))

    def test_running(self):
        memory_arbiter.write_model_service_pid(SERVICE_ID)
        self.assertTrue(memory_arbiter.model_service_alive(SERVICE_ID))

    def test_zombie(self):
        # a killed child stays a zombie until its parent reaps it, and os.kill(pid, 0) still succeeds on it
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self._register(p.pid)
        self.assertTrue(memory_arbiter.model_service_alive(SERVICE_ID))
        p.kill()
        time.sleep(0.2)
        self.assertFalse(memory_arbiter.model_service_alive(SERVICE_ID))
        p.wait()

    def test_reaped(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self._register(p.pid)
        self.assertFalse(memory_arbiter.model_service_alive(SERVICE_ID))


class ActivationFailedTest(unittest.TestCase):
    def test_hierarchy(self):
        # the engine's scheduler catches ActivationFailed: both kinds roll back and answer success=False
        self.assertTrue(issubclass(memory_arbiter.ActivationOutOfMemory, memory_arbiter.ActivationFailed))
        self.assertTrue(issubclass(memory_arbiter.ModelServiceUnavailable, memory_arbiter.ActivationFailed))


if __name__ == "__main__":
    unittest.main()
