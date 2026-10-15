"""Exercises Prism's model switching on a running 2-model server (GPU 0): deactivate/activate, preemption
(RECOMPUTE / RETURN) and memory pool resize, checking that memory is released and outputs are unchanged.

Usage: python3 polyaxon/test_switching.py <port> [--elastic]
Exit code = number of failed checks.
"""
import subprocess
import sys
import threading
import time

import requests

URL = f"http://127.0.0.1:{sys.argv[1]}"
ELASTIC = "--elastic" in sys.argv
PROMPT = "The history of the city of Rome begins"
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        failures.append(name)


def gpu_used_gb():
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"]
    )
    return int(out.decode().strip()) / 1024


def generate(model, max_new_tokens=32, timeout=600):
    r = requests.post(
        f"{URL}/generate",
        json={
            "text": PROMPT,
            "model": model,
            "sampling_params": {"temperature": 0, "max_new_tokens": max_new_tokens, "ignore_eos": True},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post(path, **payload):
    r = requests.post(f"{URL}/{path}", json=payload, timeout=600)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text


def wait_settled(seconds=3):
    time.sleep(seconds)


ref = {m: generate(m)["text"] for m in ("model_1", "model_2")}
ref_long = generate("model_2", max_new_tokens=400)
check("reference generation", all(ref.values()), repr(ref["model_2"][:60]))

# 1. Deactivate releases the model's GPU memory (weights and KV); the other model keeps serving.
# 64 concurrent requests first, so that elastic (kvcached) KV memory is mapped (~3 GB for an 8B model).
load = [threading.Thread(target=generate, args=("model_2", 400)) for _ in range(64)]
[t.start() for t in load]
time.sleep(4)
before = gpu_used_gb()
tic = time.time()
out = post("deactivate", model_name="model_2", gpu_id=0, preempt=False)
t_deact = time.time() - tic
[t.join() for t in load]
wait_settled()
after = gpu_used_gb()
weights = out.get("memory_usage", {}).get("model_weights_memory", 0)
check("deactivate success", out.get("success") is True, f"{t_deact:.2f}s {out}")
check("deactivate frees weights + KV", before - after > weights + 1.5, f"{before:.1f} -> {after:.1f} GB, weights {weights:.1f} GB")
check("KV reported released", out.get("memory_usage", {}).get("memory_pool_memory", 1) < 0.1)
check("other model still serves", generate("model_1")["text"] == ref["model_1"])

# 2. Activate restores the weights exactly (greedy output unchanged).
tic = time.time()
out = post("activate", model_name="model_2", gpu_id=0)
t_act = time.time() - tic
check("activate success", out.get("success") is True, f"{t_act:.2f}s {out}")
check("output unchanged after reactivation", generate("model_2")["text"] == ref["model_2"])
check("re-activating an active model fails", post("activate", model_name="model_2", gpu_id=0).get("success") is False)

# 3. RECOMPUTE: a running request survives a deactivate/activate cycle and completes.
res = {}
th = threading.Thread(target=lambda: res.update(out=generate("model_2", max_new_tokens=400)))
th.start()
time.sleep(1.5)
out = post("deactivate", model_name="model_2", gpu_id=0, preempt=True, preempt_mode="RECOMPUTE")
check("deactivate RECOMPUTE success", out.get("success") is True)
time.sleep(2)
check("request held while deactivated", th.is_alive())
post("activate", model_name="model_2", gpu_id=0)
th.join(timeout=600)
o = res.get("out", {})
n = o.get("meta_info", {}).get("completion_tokens")
check("RECOMPUTE request completes all tokens", n == 400, f"completion_tokens={n}")
got = o.get("text", "")
i = next((k for k, (a, b) in enumerate(zip(got, ref_long["text"])) if a != b), min(len(got), len(ref_long["text"])))
# The continuation recomputes the KV of the generated tokens in one prefill, which differs numerically
# (bf16) from the KV built during decode, so greedy decoding may eventually pick another token (SGLang's
# RECOMPUTE has the same property). What must hold is a seamless splice: the request is preempted after
# ~1.5 s (~100 tokens, ~450 chars), so the text must still match well past that point.
check("RECOMPUTE output matches across the splice", i >= 800, f"first difference at char {i}")
print(
    "[INFO] RECOMPUTE output equals uninterrupted output:",
    got == ref_long["text"],
    "" if got == ref_long["text"] else f"first difference at char {i} of {len(ref_long['text'])}"
    f"\n  got: {got[max(0, i - 60):i + 60]!r}\n  ref: {ref_long['text'][max(0, i - 60):i + 60]!r}",
    flush=True,
)

# 4. RETURN: the running request finishes early with what it has.
res = {}
th = threading.Thread(target=lambda: res.update(out=generate("model_2", max_new_tokens=400)))
th.start()
time.sleep(1.5)
out = post("deactivate", model_name="model_2", gpu_id=0, preempt=True, preempt_mode="RETURN")
th.join(timeout=60)
o = res.get("out", {})
n = o.get("meta_info", {}).get("completion_tokens", 0)
fr = o.get("meta_info", {}).get("finish_reason")
check("RETURN finishes request early", 0 < n < 400 and fr and fr.get("type") == "length", f"tokens={n} reason={fr}")
check("RETURN text is a prefix of the full output", ref_long["text"].startswith(o.get("text", "x")))
post("activate", model_name="model_2", gpu_id=0)
check("serves after RETURN cycle", generate("model_2")["text"] == ref["model_2"])

# 5. Resize (elastic only) and activation with a memory pool size.
if ELASTIC:
    post("resize_mem_pool", model_name="model_1", memory_pool_size=4)
    check("serves after resize to 4 GB", generate("model_1")["text"] == ref["model_1"])
    post("resize_mem_pool", model_name="model_1", memory_pool_size=None)
    post("deactivate", model_name="model_2", gpu_id=0)
    out = post("activate", model_name="model_2", gpu_id=0, memory_pool_size=8)
    check("activate with memory_pool_size", out.get("success") is True)
    check("serves after sized activation", generate("model_2")["text"] == ref["model_2"])

print(f"deactivate {t_deact:.2f}s, activate {t_act:.2f}s; failures: {failures}")
sys.exit(len(failures))
