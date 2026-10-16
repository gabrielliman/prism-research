"""Exercises Prism's worker pool on a running server (--enable-worker-pool, GPU scheduler on).

Usage: python3 polyaxon/test_worker_pool.py <port> <num_gpus>
Config (polyaxon/configs/worker_pool_test.json): model_1 (8B) and model_2 (3B) on GPU 0, model_3 (3B)
off; 2 workers per GPU. With the worker pool the request handler forwards activate/deactivate to the
GPU scheduler and returns at once, so the test waits on observable effects (GPU memory, generation).
Exit code = number of failed checks.
"""
import subprocess
import sys
import threading
import time

import requests

URL = f"http://127.0.0.1:{sys.argv[1]}"
NUM_GPUS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
PROMPT = "The history of the city of Rome begins"
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        failures.append(name)


def gpu_used_gb(gpu):
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", str(gpu)]
    )
    return int(out.decode().strip()) / 1024


def generate(model, max_new_tokens=32, timeout=600):
    r = requests.post(
        f"{URL}/generate",
        json={"text": PROMPT, "model": model,
              "sampling_params": {"temperature": 0, "max_new_tokens": max_new_tokens, "ignore_eos": True}},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post(path, **payload):
    return requests.post(f"{URL}/{path}", json=payload, timeout=600).json()


def wait_memory(gpu, cond, timeout=60):
    tic = time.time()
    while time.time() - tic < timeout:
        if cond(gpu_used_gb(gpu)):
            return time.time() - tic
        time.sleep(0.2)
    return None


def activate_and_time(model, gpu):
    """Client-observed activation latency: activate request -> first generated response."""
    tic = time.time()
    post("activate", model_name=model, gpu_id=gpu, instance_idx=gpu)
    out = generate(model)
    return time.time() - tic, out["text"]


ref = {m: generate(m)["text"] for m in ("model_1", "model_2")}
check("initial models serve", all(ref.values()))

# 1. Deactivate model_2: its slot tears the engine down and frees the GPU memory.
before = gpu_used_gb(0)
post("deactivate", model_name="model_2", gpu_id=0, instance_idx=0, preempt=False)
t = wait_memory(0, lambda used: before - used > 5)
check("deactivate frees the slot's GPU memory", t is not None,
      f"{before:.1f} -> {gpu_used_gb(0):.1f} GB in {t if t is None else round(t, 2)}s")

# 2. A model that was never active starts on the free slot.
t3, text3 = activate_and_time("model_3", 0)
check("activate a never-active model on a free slot", bool(text3), f"{t3:.2f}s to first response")

# 3. Swap: model_3 out, model_2 back (on whichever slot is free); output identical.
post("deactivate", model_name="model_3", gpu_id=0, instance_idx=0, preempt=False)
wait_memory(0, lambda used: used < before - 5)
t2, text2 = activate_and_time("model_2", 0)
check("reactivated model gives the same output", text2 == ref["model_2"], f"{t2:.2f}s to first response")

# 4. RECOMPUTE across slots: progress travels with the request through Redis.
res = {}
th = threading.Thread(target=lambda: res.update(out=generate("model_2", max_new_tokens=400)))
th.start()
time.sleep(1.5)
post("deactivate", model_name="model_2", gpu_id=0, instance_idx=0, preempt=True, preempt_mode="RECOMPUTE")
time.sleep(2)
check("request held while its model is inactive", th.is_alive())
post("activate", model_name="model_2", gpu_id=0, instance_idx=0)
th.join(timeout=600)
n = res.get("out", {}).get("meta_info", {}).get("completion_tokens")
check("RECOMPUTE request completes all tokens after reactivation", n == 400, f"completion_tokens={n}")

# 5. Migration (2 GPUs): model_2 leaves GPU 0 and is activated on GPU 1 (what the global policy does).
if NUM_GPUS > 1:
    before1 = gpu_used_gb(1)
    post("deactivate", model_name="model_2", gpu_id=0, instance_idx=0, preempt=False)
    wait_memory(0, lambda used: used < before - 5)
    tm, textm = activate_and_time("model_2", 1)
    check("model migrates to GPU 1", textm == ref["model_2"], f"{tm:.2f}s to first response")
    check("GPU 1 memory grew", gpu_used_gb(1) - before1 > 3, f"{before1:.1f} -> {gpu_used_gb(1):.1f} GB")

print(f"activation to first response: model_3 {t3:.2f}s, model_2 {t2:.2f}s; failures: {failures}")
sys.exit(len(failures))
