"""Load generator for the overload scenarios (run_examples.sh steps ovl_*).

Builds a synthetic open-loop workload and sends it with the benchmark's own client
(benchmark.py: send_generate_request), so requests, SLOs and metrics match the README examples.
Unlike benchmark.py, the run ends at a deadline (duration + --drain): requests still pending then
are cancelled and recorded as unserved instead of blocking the job, which is what a starved model
or a stuck engine produces under overload.

Workload knobs:
  --models model_1 ... model_N   models to send to (uniform popularity)
  --rate R                       R req/s per model while the model is "on"
  --model-rates m=R ...          per-model rates overriding --rate (e.g. model_7=0.3)
  --cv C                         coefficient of variation of the inter-arrivals (1 = Poisson, >1 = bursts)
  --duration S                   arrival window (s)
  --input-range A B / --output-range A B   uniform token lengths (ignore_eos: output is exact)
  --groups G --phase P           models split in G contiguous groups; only one group sends at a time,
                                 rotating every P seconds (time-sharing pressure). G=1: all always on.
  --slo-ttft / --slo-tpot        per-request SLO sent to the server and used for attainment (s)
  --real-trace PKL --time-scale S  instead of the synthetic workload, Prism's e2e benchmark trace
                                 (benchmark.py --e2e-benchmark: trace.py generate_e2e_benchmark_reqs, same
                                 requests, prompts and per-model SLOs sent to the server) at time scale S;
                                 --rate is ignored and the window is the trace span (600 s) x S.
                                 Attainment still uses --slo-ttft / --slo-tpot.
  --trace-adapters N             with --real-trace: instead of the e2e benchmark's 8 adapters, the N most
                                 requested adapters of the whole trace, one per model (most requested ->
                                 --models[0]), with their prompts and lengths; SLO sent = --slo-ttft.

Writes <out>/requests.json (one row per request) and <out>/summary.json.
"""
import argparse
import asyncio
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "benchmark", "multi-model"))
from benchmark import send_generate_request, set_ulimit  # noqa: E402  (benchmark's trace.py shadows stdlib trace)
from trace import RealWorldTrace, Request, TraceConfig, dummy_prompt  # noqa: E402

TRACE_SPAN_S = 600  # real_trace.pkl arrivals span 0-600 s at time scale 1


def build_trace_requests(a):
    # As benchmark.py with --model-paths: ttft/tpot SLO scale 5 (its defaults), replication 1.
    cfg = TraceConfig(model_paths=a.models, time_scale=a.time_scale, replication=1,
                      ttft_slo_scale=5, tpot_slo_scale=5)
    reqs = RealWorldTrace(a.real_trace).generate_e2e_benchmark_reqs(cfg, num_models=len(a.models))
    reqs.sort(key=lambda r: r.arrival_time)
    for i, r in enumerate(reqs):
        r.req_id = str(i)
    return reqs


def build_adapter_trace_requests(a):
    """The a.trace_adapters most requested adapters of the real trace, one per model, in popularity order."""
    from collections import Counter

    trace = RealWorldTrace(a.real_trace).requests
    rank = lambda r: int(r.adapter_dir.split("-")[-1])
    top = [k for k, _ in Counter(rank(r) for r in trace).most_common(a.trace_adapters)]
    model_of = dict(zip(top, a.models))
    reqs = [Request(req_id="", prompt=r.prompt, prompt_len=r.prompt_len, output_len=r.output_len,
                    arrival_time=r.req_time * a.time_scale, model=model_of[rank(r)],
                    slo=a.slo_ttft, slo_ttft=a.slo_ttft, slo_tpot=a.slo_tpot)
            for r in trace if rank(r) in model_of]
    reqs.sort(key=lambda r: r.arrival_time)
    for i, r in enumerate(reqs):
        r.req_id = str(i)
    return reqs


def build_requests(a):
    if a.real_trace and a.trace_adapters:
        return build_adapter_trace_requests(a)
    if a.real_trace:
        return build_trace_requests(a)
    rng = np.random.default_rng(a.seed)
    n = len(a.models)
    groups = [a.models[i * n // a.groups:(i + 1) * n // a.groups] for i in range(a.groups)]
    reqs = []
    rates = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.model_rates)
    for g, members in enumerate(groups):
        for m in members:
            rate = rates.get(m, a.rate)
            t = 0.0
            while True:
                # Gamma inter-arrivals with coefficient of variation cv (cv=1: Poisson; cv>1: bursts),
                # as in trace.py's synthetic generator.
                t += rng.gamma(1.0 / a.cv ** 2, a.cv ** 2 / rate)
                if t >= a.duration:
                    break
                if a.groups > 1 and int(t // a.phase) % a.groups != g:
                    continue  # this model's group is off in this phase
                pl = int(rng.integers(a.input_range[0], a.input_range[1] + 1))
                ol = int(rng.integers(a.output_range[0], a.output_range[1] + 1))
                reqs.append((t, m, pl, ol))
    reqs.sort()
    return [Request(req_id=str(i), prompt=dummy_prompt(pl), prompt_len=pl, output_len=ol,
                    arrival_time=t, model=m, slo=a.slo_ttft, slo_ttft=a.slo_ttft, slo_tpot=a.slo_tpot)
            for i, (t, m, pl, ol) in enumerate(reqs)]


async def run(a, reqs):
    server = a.base_url
    start = time.perf_counter()
    tasks = []
    sent_at = {}

    async def one(r):
        sent_at[r.req_id] = time.perf_counter() - start
        return await send_generate_request(server, r)

    for r in reqs:
        await asyncio.sleep(max(0.0, start + r.arrival_time - time.perf_counter()))
        tasks.append(asyncio.create_task(one(r)))
    deadline = start + a.duration + a.drain
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - time.perf_counter()))
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    elapsed = time.perf_counter() - start
    rows = []
    for r, t in zip(reqs, tasks):
        row = {"id": r.req_id, "model": r.model, "arrival": round(r.arrival_time, 3),
               "prompt_len": r.prompt_len, "output_len": r.output_len}
        if t in pending or t.cancelled():
            row.update(status="unserved")
        else:
            o = t.result()
            row.update(status="ok" if o.success else "failed", ttft=o.ttft, tpot=o.tpot,
                       latency=o.latency, generated=o.output_len,
                       error=(o.error or "").strip().splitlines()[-1][:300] if o.error else "")
        rows.append(row)
    return rows, elapsed


def summarize(a, rows, elapsed):
    ok = [r for r in rows if r["status"] == "ok"]
    ttft = np.array([r["ttft"] for r in ok]) if ok else np.array([np.nan])
    tpot = np.array([r["tpot"] for r in ok if r["tpot"] > 0]) if ok else np.array([np.nan])
    att = [r["status"] == "ok" and r["ttft"] < a.slo_ttft and r["tpot"] < a.slo_tpot for r in rows]
    per_model = {}
    for m in a.models:
        mr = [r for r in rows if r["model"] == m]
        mok = [r for r in mr if r["status"] == "ok"]
        per_model[m] = {"sent": len(mr), "ok": len(mok),
                        "unserved": sum(r["status"] == "unserved" for r in mr),
                        "failed": sum(r["status"] == "failed" for r in mr),
                        "first_ok_arrival": min((r["arrival"] for r in mok), default=None),
                        "ttft_p50": float(np.median([r["ttft"] for r in mok])) if mok else None,
                        "slo": float(np.mean([x for x, r in zip(att, rows) if r["model"] == m])) if mr else None}
    return {
        "args": vars(a), "elapsed_s": elapsed, "sent": len(rows), "ok": len(ok),
        "failed": sum(r["status"] == "failed" for r in rows),
        "unserved": sum(r["status"] == "unserved" for r in rows),
        "offered_rps": len(rows) / a.duration, "served_rps": len(ok) / elapsed,
        "output_tok_s": sum(r["generated"] for r in ok) / elapsed,
        "ttft_mean": float(np.nanmean(ttft)), "ttft_p50": float(np.nanmedian(ttft)),
        "ttft_p99": float(np.nanpercentile(ttft, 99)),
        "tpot_mean": float(np.nanmean(tpot)), "tpot_p99": float(np.nanpercentile(tpot, 99)),
        "slo_attainment": float(np.mean(att)) if att else None,
        "per_model": per_model,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--rate", type=float)
    p.add_argument("--model-rates", nargs="*", default=[])
    p.add_argument("--duration", type=float)
    p.add_argument("--drain", type=float, default=300)
    p.add_argument("--input-range", type=int, nargs=2, default=[256, 1024])
    p.add_argument("--output-range", type=int, nargs=2, default=[128, 512])
    p.add_argument("--cv", type=float, default=1.0)
    p.add_argument("--groups", type=int, default=1)
    p.add_argument("--phase", type=float, default=150)
    p.add_argument("--slo-ttft", type=float, default=1.0)
    p.add_argument("--slo-tpot", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--real-trace")
    p.add_argument("--time-scale", type=float, default=1.0)
    p.add_argument("--trace-adapters", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if a.real_trace:
        a.duration = TRACE_SPAN_S * a.time_scale
    elif a.rate is None or a.duration is None:
        p.error("--rate and --duration are required without --real-trace")
    set_ulimit()  # as benchmark.py does: one socket per in-flight request
    reqs = build_requests(a)
    print(f"{len(reqs)} requests over {a.duration:.0f}s for {len(a.models)} models "
          f"(offered {len(reqs) / a.duration:.2f} req/s), deadline +{a.drain:.0f}s", flush=True)
    rows, elapsed = asyncio.run(run(a, reqs))
    s = summarize(a, rows, elapsed)
    os.makedirs(a.out, exist_ok=True)
    json.dump(rows, open(os.path.join(a.out, "requests.json"), "w"))
    json.dump(s, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    print(f"sent {s['sent']} ok {s['ok']} failed {s['failed']} unserved {s['unserved']} | "
          f"offered {s['offered_rps']:.2f} served {s['served_rps']:.2f} req/s, {s['output_tok_s']:.0f} tok/s | "
          f"TTFT p50/p99 {s['ttft_p50']*1000:.0f}/{s['ttft_p99']*1000:.0f} ms | TPOT mean {s['tpot_mean']*1000:.1f} ms | "
          f"SLO {100 * (s['slo_attainment'] or 0):.1f}%", flush=True)
    for m, v in s["per_model"].items():
        print(f"  {m}: sent {v['sent']} ok {v['ok']} unserved {v['unserved']} failed {v['failed']} "
              f"first ok at {v['first_ok_arrival']} SLO {100 * (v['slo'] or 0):.0f}%", flush=True)


if __name__ == "__main__":
    main()
