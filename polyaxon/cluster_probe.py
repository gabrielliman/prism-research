"""Standardized node/GPU performance probe (2026-10-30), to characterize how the shared Polyaxon node's speed varies.

Usage: python3 polyaxon/cluster_probe.py <out dir> [--reps 3]

Every benchmark is fixed (same sizes, same seeds) so results are comparable across runs and days. Writes
<out>/probe.json with the median and all repetitions of each metric:
  cpu_py_loop_s          seconds for a fixed pure-Python loop (one core; the SGLang scheduler is Python)
  launch_us              µs per tiny CUDA kernel launch (torch.add on 1 element, 20k launches, then sync)
  matmul_tflops          bf16 8192^3 matmul throughput (GPU compute)
  hbm_gbs                device-to-device copy of 4 GiB (GPU memory bandwidth)
  h2d_pinned_gbs / d2h_pinned_gbs / h2d_pageable_gbs   2 GiB host<->device copies (PCIe + host memory)
  host_memcpy_gbs        numpy copy of 2 GiB in host memory
  decode_b1_ms / decode_b32_ms   eager decode step of a Llama-3.1-8B-shaped model with random weights
                         (no CUDA graph, like Prism's runs: --disable-cuda-graph), batch 1 and 32, 512-token context
  decode_b1_graph_ms     the same batch-1 step captured in a CUDA graph (removes the CPU launch cost)
The ratio decode_b1_ms / decode_b1_graph_ms separates a CPU-side slowdown (launch-bound) from a GPU-side one.
With --pin-label <label> (run under taskset by cluster_probe.sh) only cpu_py_loop_s, launch_us and decode_b1_ms are
measured, into <out>/probe_pin_<label>.json: pinned to the GPU's local NUMA node vs the remote one.
"""
import json
import os
import statistics
import sys
import time

import numpy as np
import torch


def timeit(fn, reps):
    out = []
    for _ in range(reps):
        out.append(fn())
    return out


def cpu_py_loop():
    t = time.perf_counter()
    s = 0
    for i in range(20_000_000):
        s += i ^ (i >> 3)
    return time.perf_counter() - t


def launch_us():
    x = torch.zeros(1, device="cuda")
    torch.cuda.synchronize()
    n = 20_000
    t = time.perf_counter()
    for _ in range(n):
        x.add_(1)
    torch.cuda.synchronize()
    return (time.perf_counter() - t) / n * 1e6


def matmul_tflops():
    a = torch.randn(8192, 8192, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(8192, 8192, device="cuda", dtype=torch.bfloat16)
    for _ in range(3):
        a @ b
    torch.cuda.synchronize()
    n = 50
    t = time.perf_counter()
    for _ in range(n):
        a @ b
    torch.cuda.synchronize()
    return 2 * 8192**3 * n / (time.perf_counter() - t) / 1e12


def hbm_gbs():
    n = 4 << 30
    a = torch.empty(n, dtype=torch.uint8, device="cuda")
    b = torch.empty_like(a)
    b.copy_(a)
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(10):
        b.copy_(a)
    torch.cuda.synchronize()
    return 2 * n * 10 / (time.perf_counter() - t) / 1e9  # read + write


def copy_gbs(kind):
    n = 2 << 30
    if kind == "h2d_pinned":
        src, dst = torch.empty(n, dtype=torch.uint8, pin_memory=True), torch.empty(n, dtype=torch.uint8, device="cuda")
    elif kind == "d2h_pinned":
        src, dst = torch.empty(n, dtype=torch.uint8, device="cuda"), torch.empty(n, dtype=torch.uint8, pin_memory=True)
    else:  # h2d_pageable
        src, dst = torch.ones(n, dtype=torch.uint8), torch.empty(n, dtype=torch.uint8, device="cuda")
    dst.copy_(src)
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(5):
        dst.copy_(src, non_blocking=False)
    torch.cuda.synchronize()
    return n * 5 / (time.perf_counter() - t) / 1e9


def host_memcpy_gbs():
    a = np.ones(2 << 30, dtype=np.uint8)
    b = np.empty_like(a)
    np.copyto(b, a)
    t = time.perf_counter()
    for _ in range(5):
        np.copyto(b, a)
    return 2 * a.nbytes * 5 / (time.perf_counter() - t) / 1e9


def build_model():
    from transformers import LlamaConfig, LlamaForCausalLM

    cfg = LlamaConfig(hidden_size=4096, intermediate_size=14336, num_hidden_layers=32, num_attention_heads=32,
                      num_key_value_heads=8, vocab_size=128256, max_position_embeddings=8192, rope_theta=500000.0)
    torch.manual_seed(0)
    with torch.device("cuda"):
        model = LlamaForCausalLM(cfg).to(torch.bfloat16).eval()
    return model


@torch.inference_mode()
def decode_ms(model, batch, ctx=512, steps=64, graph=False):
    from transformers import StaticCache

    cache = StaticCache(config=model.config, max_batch_size=batch, max_cache_len=ctx + steps + 8,
                        device="cuda", dtype=torch.bfloat16)
    ids = torch.randint(0, 32000, (batch, ctx), device="cuda")
    pos = torch.arange(ctx, device="cuda")
    model(input_ids=ids, past_key_values=cache, cache_position=pos, use_cache=True)
    tok = torch.randint(0, 32000, (batch, 1), device="cuda")
    p = torch.tensor([ctx], device="cuda")

    def step():
        return model(input_ids=tok, past_key_values=cache, cache_position=p, use_cache=True).logits

    if graph:
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                step()
        torch.cuda.current_stream().wait_stream(s)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g):
            step()
        run = g.replay
    else:
        run = step
    for _ in range(5):
        run()
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(steps):
        run()  # same position each step: fixed work per step, no cache growth
    torch.cuda.synchronize()
    return (time.perf_counter() - t) / steps * 1e3


def numa_main(out, label):
    """Only the CPU-sensitive benchmarks, for a run pinned with taskset (cluster_probe.sh: local vs remote NUMA)."""
    res = {"pin": label, "cpus_affinity": sorted(os.sched_getaffinity(0))[:1] + sorted(os.sched_getaffinity(0))[-1:]}
    for name, fn in [("cpu_py_loop_s", cpu_py_loop), ("launch_us", launch_us)]:
        vals = timeit(fn, 3)
        res[name] = {"median": statistics.median(vals), "all": vals}
    model = build_model()
    vals = timeit(lambda: decode_ms(model, batch=1), 3)
    res["decode_b1_ms"] = {"median": statistics.median(vals), "all": vals}
    print(json.dumps(res), flush=True)
    json.dump(res, open(os.path.join(out, f"probe_pin_{label}.json"), "w"), indent=1)


def main():
    out = sys.argv[1]
    if "--pin-label" in sys.argv:
        return numa_main(out, sys.argv[sys.argv.index("--pin-label") + 1])
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else 3
    os.makedirs(out, exist_ok=True)
    res = {"start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "gpu": torch.cuda.get_device_name(0),
           "torch": torch.__version__, "cpus_affinity": len(os.sched_getaffinity(0)), "cpus_node": os.cpu_count()}
    benches = [("cpu_py_loop_s", cpu_py_loop), ("launch_us", launch_us), ("matmul_tflops", matmul_tflops),
               ("hbm_gbs", hbm_gbs), ("h2d_pinned_gbs", lambda: copy_gbs("h2d_pinned")),
               ("d2h_pinned_gbs", lambda: copy_gbs("d2h_pinned")), ("h2d_pageable_gbs", lambda: copy_gbs("h2d_pageable")),
               ("host_memcpy_gbs", host_memcpy_gbs)]
    for name, fn in benches:
        vals = timeit(fn, reps)
        res[name] = {"median": statistics.median(vals), "all": vals}
        print(f"{name}: {statistics.median(vals):.3f} {['%.3f' % v for v in vals]}", flush=True)
        torch.cuda.empty_cache()
    model = build_model()
    for name, kw in [("decode_b1_ms", dict(batch=1)), ("decode_b32_ms", dict(batch=32)),
                     ("decode_b1_graph_ms", dict(batch=1, graph=True))]:
        vals = timeit(lambda: decode_ms(model, **kw), reps)
        res[name] = {"median": statistics.median(vals), "all": vals}
        print(f"{name}: {statistics.median(vals):.3f} {['%.3f' % v for v in vals]}", flush=True)
    res["end_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(res, open(os.path.join(out, "probe.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
