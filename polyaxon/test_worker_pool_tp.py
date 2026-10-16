"""Exercises a tensor-parallel model in the vLLM worker pool (polyaxon/configs/worker_pool_tp_test.json):
model_3 (Llama-3.1-8B, tp_size=2, initially inactive) next to two tp_size=1 models on GPUs 0 and 1.

Usage: python3 polyaxon/test_worker_pool_tp.py <port>
With the worker pool, activate/deactivate return at once (the GPU scheduler forwards them), so the test
waits on observable effects. Exit code = number of failed checks.
"""
import subprocess
import sys
import threading
import time

import requests

URL = f"http://127.0.0.1:{sys.argv[1]}"
PROMPT = "The history of the city of Rome begins"
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        failures.append(name)


def used(gpu):
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


def wait(cond, timeout=60):
    tic = time.time()
    while time.time() - tic < timeout:
        if cond():
            return time.time() - tic
        time.sleep(0.2)
    return None


ref = {m: generate(m)["text"] for m in ("model_1", "model_2")}
check("tp_size=1 models serve", all(ref.values()))

# 1. Activate the TP model through the pool (GPU scheduler of its first GPU, TP slot on GPUs 0-1).
b0, b1 = used(0), used(1)
tic = time.time()
post("activate", model_name="model_3", gpu_id=0, instance_idx=0)
ref3 = generate("model_3")["text"]
t_act = time.time() - tic
check("activate TP model from the pool", bool(ref3), f"{t_act:.2f}s to first response")
check("both GPUs hold a TP part", used(0) - b0 > 3 and used(1) - b1 > 3,
      f"GPU0 {b0:.1f}->{used(0):.1f} GB, GPU1 {b1:.1f}->{used(1):.1f} GB")
check("tp_size=1 models unaffected", generate("model_1")["text"] == ref["model_1"]
      and generate("model_2")["text"] == ref["model_2"])

# 2. Deactivate: both ranks release their part.
a0, a1 = used(0), used(1)
tic = time.time()
post("deactivate", model_name="model_3", gpu_id=0, instance_idx=0, preempt=False)
t = wait(lambda: a0 - used(0) > 3 and a1 - used(1) > 3)
check("deactivate frees both GPUs", t is not None,
      f"GPU0 {a0:.1f}->{used(0):.1f} GB, GPU1 {a1:.1f}->{used(1):.1f} GB in {t if t is None else round(t, 2)}s")

# 3. Reactivate: same output.
tic = time.time()
post("activate", model_name="model_3", gpu_id=0, instance_idx=0)
text = generate("model_3")["text"]
t_react = time.time() - tic
check("reactivated TP model gives the same output", text == ref3, f"{t_react:.2f}s to first response")

# 4. RECOMPUTE across a deactivate/activate cycle.
res = {}
th = threading.Thread(target=lambda: res.update(out=generate("model_3", max_new_tokens=400)))
th.start()
time.sleep(1.5)
post("deactivate", model_name="model_3", gpu_id=0, instance_idx=0, preempt=True, preempt_mode="RECOMPUTE")
time.sleep(2)
check("request held while the TP model is inactive", th.is_alive())
post("activate", model_name="model_3", gpu_id=0, instance_idx=0)
th.join(timeout=600)
n = res.get("out", {}).get("meta_info", {}).get("completion_tokens")
check("RECOMPUTE request completes all tokens", n == 400, f"completion_tokens={n}")
check("tp_size=1 models still serve", generate("model_1")["text"] == ref["model_1"])

print(f"TP activation to first response: first {t_act:.2f}s, again {t_react:.2f}s; failures: {failures}")
sys.exit(len(failures))
