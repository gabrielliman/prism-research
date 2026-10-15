"""Activation/deactivation latency and memory on a running 2-model Prism server (GPU 0).

Usage: PRISM_GPU_BASELINE_GB=<GPU memory used before the server started> \
       python3 polyaxon/compare/activation.py <port> <out.json> [cycles]
Measures, per model: client-side deactivate/activate time over `cycles` idle cycles, GPU memory freed by
a deactivation, and the GPU memory an engine still holds while deactivated (both models off).
"""
import json
import os
import subprocess
import sys
import time

import requests

URL = f"http://127.0.0.1:{sys.argv[1]}"
CYCLES = int(sys.argv[3]) if len(sys.argv) > 3 else 10
BASELINE = float(os.environ.get("PRISM_GPU_BASELINE_GB", "0"))


def gpu_used_gb():
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"]
    )
    return int(out.decode().strip()) / 1024


def post(path, **payload):
    tic = time.perf_counter()
    r = requests.post(f"{URL}/{path}", json=payload, timeout=600)
    return time.perf_counter() - tic, r.json()


def generate(model):
    r = requests.post(
        f"{URL}/generate",
        json={"text": "Hello, my name is", "model": model, "sampling_params": {"temperature": 0, "max_new_tokens": 16}},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["text"]


res = {"baseline_gb": BASELINE, "both_active_gb": gpu_used_gb(), "models": {}}
for model in ("model_1", "model_2"):
    ref = generate(model)
    d_times, a_times, freed, ok = [], [], [], True
    for _ in range(CYCLES):
        before = gpu_used_gb()
        t, out = post("deactivate", model_name=model, gpu_id=0, preempt=False)
        ok &= out.get("success") is True
        d_times.append(t)
        time.sleep(1)
        freed.append(before - gpu_used_gb())
        t, out = post("activate", model_name=model, gpu_id=0)
        ok &= out.get("success") is True
        a_times.append(t)
        ok &= generate(model) == ref  # first request after activation, output unchanged
    res["models"][model] = {
        "deactivate_s": d_times, "activate_s": a_times, "freed_gb": freed, "all_ok": bool(ok),
    }
    print(model, f"deactivate median {sorted(d_times)[len(d_times) // 2]:.3f}s",
          f"activate median {sorted(a_times)[len(a_times) // 2]:.3f}s",
          f"freed median {sorted(freed)[len(freed) // 2]:.2f} GB ok={ok}", flush=True)

# Memory held by two deactivated engines.
for model in ("model_1", "model_2"):
    post("deactivate", model_name=model, gpu_id=0, preempt=False)
time.sleep(2)
res["both_inactive_gb"] = gpu_used_gb()
res["idle_engine_gb"] = (res["both_inactive_gb"] - BASELINE) / 2
print(f"both inactive: {res['both_inactive_gb']:.2f} GB (baseline {BASELINE:.2f}) -> "
      f"{res['idle_engine_gb']:.2f} GB per deactivated engine", flush=True)
for model in ("model_1", "model_2"):
    post("activate", model_name=model, gpu_id=0)
json.dump(res, open(sys.argv[2], "w"), indent=1)
