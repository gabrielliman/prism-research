"""Measures how fast one process can switch a vLLM engine between models (the vLLM worker pool's core
operation), with the patches in sglang/multi_model/vllm_backend/vllm_patches.py.

Usage: python3 polyaxon/experiments/engine_swap.py <out.json> [rounds]
Env:   ENABLE_KVCACHED=true for elastic KV (set before start), PRISM_SWAP_MODELS="a,b" (default 3B,8B)

For each model: a cold engine from the checkpoint (reference output), the weights saved to the shared
cache, then `rounds` x (build from cache -> greedy generate -> teardown) alternating models, with and
without the profiling pass. Records phase times, GPU memory after teardown (leaks) and output equality.
"""
import contextlib
import functools
import json
import logging
import os
import sys
import time

os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")

import torch  # noqa: E402
from vllm import EngineArgs, LLMEngine, SamplingParams  # noqa: E402

from sglang.multi_model.vllm_backend import vllm_patches, weight_cache  # noqa: E402

vllm_patches.apply()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

# Phase timers: wall time spent in the main steps of LLMEngine construction (experiment only).
PHASES = {}


def _timed(owner, attr, label):
    fn = getattr(owner, attr)

    @functools.wraps(fn)
    def wrapper(*a, **k):
        tic = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            PHASES[label] = PHASES.get(label, 0.0) + time.perf_counter() - tic

    setattr(owner, attr, wrapper)


import vllm.v1.engine.llm_engine as _llm_engine  # noqa: E402
from vllm.v1.core.sched.scheduler import Scheduler as _Scheduler  # noqa: E402
from vllm.v1.engine.core import EngineCore as _EngineCore  # noqa: E402
from vllm.v1.engine.input_processor import InputProcessor as _InputProcessor  # noqa: E402
from vllm.v1.engine.output_processor import OutputProcessor as _OutputProcessor  # noqa: E402
from vllm.v1.worker.gpu_worker import Worker as _Worker  # noqa: E402

_timed(EngineArgs, "create_engine_config", "config")
_timed(_llm_engine, "renderer_from_config", "renderer/tokenizer")
_timed(_InputProcessor, "__init__", "input_processor")
_timed(_OutputProcessor, "__init__", "output_processor")
_timed(_EngineCore, "__init__", "engine_core(total)")
_timed(_Worker, "init_device", "worker.init_device")
_timed(_Worker, "load_model", "worker.load_model")
_timed(_Worker, "determine_available_memory", "worker.determine_memory(profile)")
_timed(_Worker, "initialize_from_config", "worker.init_kv_cache")
_timed(_Worker, "compile_or_warm_up_model", "worker.warmup")
_timed(_Scheduler, "__init__", "scheduler")

import gc  # noqa: E402

_gc_start = [0.0]


def _gc_cb(phase, info):
    if phase == "start":
        _gc_start[0] = time.perf_counter()
    else:
        PHASES["gc(total)"] = PHASES.get("gc(total)", 0.0) + time.perf_counter() - _gc_start[0]


gc.callbacks.append(_gc_cb)
BUILDS = [0]
OUT = sys.argv[1]
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
MODELS = os.environ.get(
    "PRISM_SWAP_MODELS", "meta-llama/Llama-3.2-3B-Instruct,meta-llama/Llama-3.1-8B-Instruct"
).split(",")
ELASTIC = os.environ.get("ENABLE_KVCACHED", "false").lower() in ("true", "1")
PROMPT = "The history of the city of Rome begins"


def gpu_used_gb():
    free, total = torch.cuda.mem_get_info()
    return (total - free) / (1 << 30)


def build(model, load_format):
    args = EngineArgs(
        model=model, load_format=load_format, enforce_eager=True, enable_prefix_caching=False,
        model_loader_extra_config={"cache_key": model} if load_format == "prism_shm" else {},
        max_model_len=-1, async_scheduling=False, disable_log_stats=True,
        gpu_memory_utilization=0.45 if ELASTIC else 0.9,
        kv_cache_memory_bytes=None if ELASTIC else 10 * (1 << 30),
    )
    PHASES.clear()
    BUILDS[0] += 1
    profile = os.environ.get("PRISM_SWAP_PROFILE") == "1" and BUILDS[0] == 5
    if profile:
        import cProfile
        import io
        import pstats

        prof = cProfile.Profile()
        prof.enable()
    tic = time.perf_counter()
    engine = LLMEngine.from_engine_args(args)
    total = time.perf_counter() - tic
    if profile:
        prof.disable()
        out = io.StringIO()
        pstats.Stats(prof, stream=out).sort_stats("cumulative").print_stats(60)
        print("PROFILE\n" + out.getvalue(), flush=True)
    print("phases", model.split("/")[-1], load_format, {k: round(v, 3) for k, v in PHASES.items()},
          "total", round(total, 3), flush=True)
    return engine, total


def generate(engine):
    tic = time.perf_counter()
    engine.add_request("r", {"prompt_token_ids": engine.get_tokenizer().encode(PROMPT)},
                       SamplingParams(temperature=0, max_tokens=64))
    text = None
    while engine.has_unfinished_requests():
        for out in engine.step():
            if out.finished:
                text = out.outputs[0].text
    return text, time.perf_counter() - tic


def model_of(engine):
    return engine.engine_core.engine_core.model_executor.driver_worker.worker.model_runner.get_model()


res = {"elastic": ELASTIC, "baseline_gb": gpu_used_gb(), "cold": {}, "swaps": [],
       "shm_size_gb": None}
refs = {}
for m in MODELS:
    engine, t = build(m, "auto")
    refs[m], tg = generate(engine)
    tic = time.perf_counter()
    weight_cache.save(model_of(engine), m)
    res["cold"][m] = {"build_s": t, "first_generate_s": tg, "cache_save_s": time.perf_counter() - tic,
                      "used_gb": gpu_used_gb()}
    vllm_patches.teardown_engine(engine)
    del engine
    res["cold"][m]["after_teardown_gb"] = gpu_used_gb()
    print("cold", m, res["cold"][m], flush=True)

FLAGS = ("PRISM_VLLM_SKIP_PROFILE", "PRISM_VLLM_CACHE_RENDERER", "PRISM_VLLM_SKIP_WARMUP")
VARIANTS = [  # (name, flags on, gc skipped during construction)
    ("base", (), False),
    ("fast_keep_warmup", ("PRISM_VLLM_SKIP_PROFILE", "PRISM_VLLM_CACHE_RENDERER"), True),
    ("fast", FLAGS, True),
]
for name, flags, fast_gc in VARIANTS:
    for f in FLAGS:
        os.environ[f] = "1" if f in flags else "0"
    for r in range(ROUNDS):
        for m in MODELS:
            with (vllm_patches.fast_build() if fast_gc else contextlib.nullcontext()):
                engine, t = build(m, "prism_shm")
            text, tg = generate(engine)
            used = gpu_used_gb()
            tic = time.perf_counter()
            vllm_patches.teardown_engine(engine)
            del engine
            td = time.perf_counter() - tic
            row = {"variant": name, "model": m.split("/")[-1], "round": r, "build_s": round(t, 3),
                   "first_generate_s": round(tg, 3), "teardown_s": round(td, 3), "used_gb": round(used, 2),
                   "after_teardown_gb": round(gpu_used_gb(), 2), "same_output": text == refs[m]}
            res["swaps"].append(row)
            print("swap", row, flush=True)

json.dump(res, open(OUT, "w"), indent=1)
ok = all(s["same_output"] for s in res["swaps"])
leak = res["swaps"][-1]["after_teardown_gb"] - res["swaps"][0]["after_teardown_gb"]
print(f"all outputs identical: {ok}; memory drift after teardown across swaps: {leak:.2f} GB")
