"""Load generator for the overload scenarios (run_examples.sh steps ovl_*).

Builds a synthetic open-loop workload and sends it with the benchmark's own client
(benchmark.py: send_generate_request), so requests, SLOs and metrics match the README examples.
Unlike benchmark.py, the run ends at a deadline (duration + --drain): requests still pending then
are cancelled and recorded as unserved instead of blocking the job, which is what a starved model
or a stuck engine produces under overload.

Workload knobs (F3: polyaxon/workloads.py builds every synthetic and normalized-trace workload, see its docstring for
--pattern zipf_drift|bursty|diurnal|trace, --lengths, --batch-frac and the seeds):
  --models model_1 ... model_N   models to send to (uniform popularity)
  --rate R                       R req/s per model while the model is "on"
  --model-rates m=R ...          per-model rates overriding --rate (e.g. model_7=0.3)
  --cv C                         coefficient of variation of the inter-arrivals (1 = Poisson, >1 = bursts)
  --duration S                   arrival window (s)
  --input-range A B / --output-range A B   uniform token lengths (ignore_eos: output is exact)
  --groups G --phase P           models split in G contiguous groups; only one group sends at a time,
                                 rotating every P seconds (time-sharing pressure). G=1: all always on.
  --slo-ttft / --slo-tpot        per-request SLO sent to the server and used for attainment (s)
  --slo-spec FAM:k=v,...         F6a.1: instead, each request's SLO from a family and level (slo_metrics.py: S1, S2,
                                 S2M, S3, S6, S6P, S2L), the same rule the metrics use: the server gets the TTFT SLO (its
                                 deadline = arrival + SLO_TTFT), and attainment uses both. Needs --slo-config (the
                                 server's model config: model_name -> model_path) and --slo-scenario (ovl_* step, the
                                 key of reports/registro/latencia_ded.json). Overrides --slo-ttft/--slo-tpot, also for
                                 --real-trace.
  --real-trace PKL --time-scale S  instead of the synthetic workload, Prism's e2e benchmark trace
                                 (benchmark.py --e2e-benchmark: trace.py generate_e2e_benchmark_reqs, same
                                 requests, prompts and per-model SLOs sent to the server) at time scale S;
                                 --rate is ignored and the window is the trace span (600 s) x S.
                                 Attainment still uses --slo-ttft / --slo-tpot.
  --trace-adapters N             with --real-trace: instead of the e2e benchmark's 8 adapters, the N most
                                 requested adapters of the whole trace, one per model (most requested ->
                                 --models[0]), with their prompts and lengths; SLO sent = --slo-ttft.
  --only-model M --send-as N     build the whole workload as above (same --models, seed and level, so the same
                                 requests), then send only model M's requests, to model N (F2.10: the model's own
                                 workload on a dedicated GPU, the Prism paper's SLO base, run_examples.sh
                                 PRISM_OVL_DEDICATED); rows keep M in "workload_model"

Final states (requests.json "status"): ok, unserved (cancelled at the deadline: expired), refused (the server
answered with REFUSED_MARK in the error, the admission-control contract for F7; counts as a violation), failed.

Writes <out>/requests.json (one row per request: workload, status, TTFT/TPOT/latency, and since F2.1 the send time,
the SLO, deadline and class, the client-side first-token time and the server's wall-clock timestamps) and
<out>/summary.json (load_start_wall: wall clock of the load start).
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

import workloads  # noqa: E402

REFUSED_MARK = "PRISM_REFUSED"  # F3.1: an admission policy (F7) refuses a request with an error containing this
BATCH_SLO_TPOT = 3600.0  # C9 batch class: no TPOT limit (sent as a value the server accepts)
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
    reqs, a.workload_info = workloads.build(a)
    out = []
    for i, (t, m, pl, ol, cls) in enumerate(reqs):
        r = Request(req_id=str(i), prompt=dummy_prompt(pl), prompt_len=pl, output_len=ol,
                    arrival_time=t, model=m, slo=a.slo_ttft, slo_ttft=a.slo_ttft, slo_tpot=a.slo_tpot)
        r.slo_class = cls
        out.append(r)
    return out


def apply_classes(a, reqs):
    """C9: batch requests get --batch-slo-ttft and no TPOT limit; interactive ones keep the SLO already set."""
    for r in reqs:
        if getattr(r, "slo_class", "interactive") == "batch":
            r.slo = r.slo_ttft = a.batch_slo_ttft
            r.slo_tpot = BATCH_SLO_TPOT


def apply_slo_spec(a, reqs):
    """F6a.1: per-request (SLO_TTFT, SLO_TPOT) from --slo-spec, with slo_metrics.py's rule and bases."""
    import slo_metrics as sm

    fam, p = sm.parse_slo(a.slo_spec)
    refs = sm.Refs()
    path = {m["model_name"]: m["model_path"] for m in json.load(open(a.slo_config))}
    bases = sm.bases_for(fam, a.slo_scenario, path, refs)
    for r in reqs:
        ttft, tpot = sm.slo_of({"model": r.model, "prompt_len": r.prompt_len}, path[r.model], fam, p, refs,
                               bases[r.model])
        r.slo = r.slo_ttft = ttft
        r.slo_tpot = tpot


async def run(a, reqs):
    server = a.base_url
    start = time.perf_counter()
    start_wall = time.time()  # wall clock of the load start (same clock as the server's timestamps: same container)
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
        # F2.1: send time (s from the load start, V11), the request's SLO and deadline, and for answered requests the
        # client-side first-token time (V9) and the server's wall-clock timestamps (V10, load start alignment).
        row = {"id": r.req_id, "model": r.model, "arrival": round(r.arrival_time, 3),
               "prompt_len": r.prompt_len, "output_len": r.output_len,
               "sent": round(sent_at[r.req_id], 4) if r.req_id in sent_at else None,
               "slo_ttft": r.slo_ttft, "slo_tpot": r.slo_tpot, "deadline": round(r.arrival_time + r.slo_ttft, 3) if r.slo_ttft is not None else None,
               "slo_class": getattr(r, "slo_class", "interactive")}
        if a.only_model:
            row["workload_model"] = a.only_model
        if t in pending or t.cancelled():
            row.update(status="unserved")
        else:
            o = t.result()
            refused = not o.success and REFUSED_MARK in (o.error or "")
            row.update(status="ok" if o.success else "refused" if refused else "failed", ttft=o.ttft, tpot=o.tpot,
                       latency=o.latency, generated=o.output_len,
                       error=(o.error or "").strip().splitlines()[-1][:300] if o.error else "",
                       client_ttft=o.client_ttft or None, server_arrival=o.arrival_time or None,
                       server_prefill_finish=o.prefill_finish_time or None, server_finish=o.finish_time or None)
        rows.append(row)
    return rows, elapsed, start_wall


def summarize(a, rows, elapsed):
    ok = [r for r in rows if r["status"] == "ok"]
    ttft = np.array([r["ttft"] for r in ok]) if ok else np.array([np.nan])
    tpot = np.array([r["tpot"] for r in ok if r["tpot"] > 0]) if ok else np.array([np.nan])
    # with --slo-spec each request's own SLO; otherwise --slo-ttft/--slo-tpot (as before, also for --real-trace)
    st = (lambda r: (r["slo_ttft"], r["slo_tpot"])) if a.slo_spec else (lambda r: (a.slo_ttft, a.slo_tpot))
    att = [r["status"] == "ok" and r["ttft"] < st(r)[0] and r["tpot"] < st(r)[1] for r in rows]
    per_model = {}
    for m in ([a.send_as or a.only_model] if a.only_model else a.models):
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
        "refused": sum(r["status"] == "refused" for r in rows),
        "workload_info": getattr(a, "workload_info", {}),
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
    workloads.add_args(p)
    p.add_argument("--drain", type=float, default=300)
    p.add_argument("--slo-ttft", type=float, default=1.0)
    p.add_argument("--slo-tpot", type=float, default=0.1)
    p.add_argument("--slo-spec")
    p.add_argument("--slo-config")
    p.add_argument("--slo-scenario")
    p.add_argument("--real-trace")
    p.add_argument("--time-scale", type=float, default=1.0)
    p.add_argument("--trace-adapters", type=int, default=0)
    p.add_argument("--only-model")
    p.add_argument("--send-as")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if a.real_trace:
        a.duration = TRACE_SPAN_S * a.time_scale
    else:
        workloads.check_args(p, a)
    set_ulimit()  # as benchmark.py does: one socket per in-flight request
    reqs = build_requests(a)
    if a.slo_spec:
        if not (a.slo_config and a.slo_scenario):
            p.error("--slo-spec needs --slo-config and --slo-scenario")
        apply_slo_spec(a, reqs)
    if a.batch_frac:
        apply_classes(a, reqs)
        s = sorted(r.slo_ttft for r in reqs)
        print(f"SLO {a.slo_spec} ({a.slo_scenario}): TTFT {s[0]:.3f}-{s[-1]:.3f} s, "
              f"TPOT {min(r.slo_tpot for r in reqs):.4f}-{max(r.slo_tpot for r in reqs):.4f} s", flush=True)
    if a.only_model:
        reqs = [r for r in reqs if r.model == a.only_model]
        for r in reqs:
            r.model = a.send_as or a.only_model
    print(f"{len(reqs)} requests over {a.duration:.0f}s for {len(a.models)} models "
          f"(offered {len(reqs) / a.duration:.2f} req/s), deadline +{a.drain:.0f}s", flush=True)
    rows, elapsed, start_wall = asyncio.run(run(a, reqs))
    s = summarize(a, rows, elapsed)
    s["load_start_wall"] = start_wall
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
