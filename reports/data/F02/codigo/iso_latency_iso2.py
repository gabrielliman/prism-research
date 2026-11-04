"""Reference latencies of one resident model alone on the GPU (F2.10, F2.4; PLANO_AGENTE.md section 5.4).

Usage: python3 polyaxon/iso_latency.py --base-url URL --model model_1 --out <dir> [--lengths 64 ... 4096]
                                       [--per-length 10] [--bursts 2 4 8 16] [--burst-lengths 256 1024]
                                       [--tpot-streams 1 8] [--tpot-reqs 4]

Run against a server with only this model, already active, and nothing else sending. Phases, all with exact output
lengths (ignore_eos, as overload_load.py) and the benchmark's client (benchmark.py send_generate_request):
  ttft    one request at a time, --per-length requests per prompt length, output 4 tokens: TTFT_iso(m, L)
  burst   k requests sent together (same prompt length), 5 bursts per (k, L), output 4 tokens: the batch is prefilled
          together, so the last TTFT of a burst is the prefill time of k·L tokens (prefill estimator p̂, F2.4)
  tpot    c closed-loop streams × --tpot-reqs requests, prompt 512, output 256: TPOT_iso(m) with batch c
Writes <out>/iso.json: one row per request (phase, k or c, prompt_len, output_len, ttft (server), client_ttft, tpot,
latency) plus the arguments. Fitting: polyaxon/iso_fit.py.
"""
import argparse
import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "benchmark", "multi-model"))
from benchmark import send_generate_request, set_ulimit  # noqa: E402
from trace import Request, dummy_prompt  # noqa: E402

SLO = 1000.0  # never abort: these are latency measurements, not SLO runs


def req(i, model, pl, ol):
    return Request(req_id=f"iso{i}", prompt=dummy_prompt(pl), prompt_len=pl, output_len=ol, arrival_time=0.0,
                   model=model, slo=SLO, slo_ttft=SLO, slo_tpot=SLO)


def row(phase, group, r, o):
    return {"phase": phase, "group": group, "prompt_len": r.prompt_len, "output_len": r.output_len,
            "ok": bool(o.success), "ttft": o.ttft, "client_ttft": o.client_ttft or None, "tpot": o.tpot,
            "latency": o.latency, "error": (o.error or "")[-200:]}


async def run(a):
    url, rows, n = a.base_url, [], 0

    def nxt():
        nonlocal n
        n += 1
        return n

    for _ in range(3):  # warm-up, not recorded
        await send_generate_request(url, req(nxt(), a.model, 256, 8))
    for pl in a.lengths:
        for _ in range(a.per_length):
            r = req(nxt(), a.model, pl, 4)
            rows.append(row("ttft", 1, r, await send_generate_request(url, r)))
    for k in a.bursts:
        for pl in a.burst_lengths:
            for _ in range(5):
                rs = [req(nxt(), a.model, pl, 4) for _ in range(k)]
                outs = await asyncio.gather(*(send_generate_request(url, r) for r in rs))
                rows += [row("burst", k, r, o) for r, o in zip(rs, outs)]
                await asyncio.sleep(0.5)
    for c in a.tpot_streams:
        async def stream():
            out = []
            for _ in range(a.tpot_reqs):
                r = req(nxt(), a.model, 512, 256)
                out.append(row("tpot", c, r, await send_generate_request(url, r)))
            return out
        for part in await asyncio.gather(*(stream() for _ in range(c))):
            rows += part
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lengths", type=int, nargs="+", default=[64, 128, 256, 512, 1024, 2048, 4096])
    p.add_argument("--per-length", type=int, default=10)
    p.add_argument("--bursts", type=int, nargs="+", default=[2, 4, 8, 16])
    p.add_argument("--burst-lengths", type=int, nargs="+", default=[256, 1024])
    p.add_argument("--tpot-streams", type=int, nargs="+", default=[1, 8])
    p.add_argument("--tpot-reqs", type=int, default=4)
    a = p.parse_args()
    set_ulimit()
    t = time.time()
    load = lambda: open("/proc/loadavg").read().split()[:3] if os.path.exists("/proc/loadavg") else None
    load0 = load()  # node CPU load: decode without CUDA graphs is CPU-bound, so contention shows in TPOT
    rows = asyncio.run(run(a))
    os.makedirs(a.out, exist_ok=True)
    json.dump({"args": vars(a), "elapsed_s": time.time() - t, "loadavg_start": load0, "loadavg_end": load(),
               "rows": rows}, open(os.path.join(a.out, "iso.json"), "w"))
    bad = sum(not r["ok"] for r in rows)
    print(f"{len(rows)} requests in {time.time() - t:.0f} s, {bad} failed", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
