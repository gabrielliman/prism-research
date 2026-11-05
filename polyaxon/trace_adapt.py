"""Trace adaptation (F3.3, PLANO_AGENTE.md section 5.3 protocol): raw public trace -> normalized trace for
overload_load.py --pattern trace (workloads.py), plus statistics before and after the transformation.

Usage (opt-env Python; datasets under /mnt/scratch/scheduler/datasets/<id>/, never in git):
  trace_adapt.py azfn   --src invocations_per_function_md.anon.d01.csv --out polyaxon/traces/T3_azfn.csv.gz
                        [--n 12 --window-min 60 --start-min 600 --target-rate 2.0 --span 600 --lengths <norm trace>]
  trace_adapt.py window --src AzureLLMInferenceTrace_conv.csv --kind azllm --out polyaxon/traces/T4_azllm.csv.gz
                        [--n 12 --win 30 --span 600]
  trace_adapt.py window --src BurstGPT_1.csv --kind burstgpt --out polyaxon/traces/T5_burst.csv.gz
                        [--n 12 --win 600 --span 600 --filter "ChatGPT/API log"]
  trace_adapt.py lengths --src AzureLLMInferenceTrace_conv.csv --out polyaxon/traces/L_azllm_conv.csv.gz
                        (length table for --lengths empirical:<file>: every request's (prompt, output), arrival 0)

Entity rules (section 5.3, items 2-4; decision D28):
  azfn    T3. Azure Functions 2019 has per-minute invocation counts per function, no tokens. Take the HTTP-triggered
          functions (user-facing requests) in a --window-min window starting at minute --start-min of the day, rank
          them by invocations in the window, and keep --n ranks log-spaced over a popularity band whose top/bottom
          invocation ratio is --skew (default 8, about T1's 23%/2.8%), the band placed so the total is closest to
          target-rate x span (no thinning: counts, popularity ratios and per-minute shape are the real ones). Each
          minute is compressed to span / window-min seconds and its invocations are placed uniformly at random in it
          (the trace has no sub-minute times; seed 0). Lengths: drawn from --lengths (default T4's length table).
  window  T4/T5. A single-service trace (Azure LLM 2023: one service per file; BurstGPT: one model + log type,
          --filter) has no per-model split. Entity i = the i-th consecutive --win-second window from an anchor hour:
          --anchor busiest (the hour with most requests; T4, a one-hour trace) or --anchor target (the first hour
          whose n x win s block carries --target-rate at the final time scale; T5, 61 days); each window's arrivals are shifted to 0 and stretched by
          span / win. Every entity keeps a real arrival process, its CV and its real lengths; the popularity is
          the natural rate variation between windows (ranks by count). Splitting one stream at random instead would
          thin it and pull its CV toward 1. BurstGPT timestamps are whole seconds: jitter U[0, 1) s (seed 0),
          failed requests (0 response tokens) dropped.
Statistics (<out>.stats.json, section 5.3 item 6): per entity, before (original time; azfn: per-minute counts) and
after (normalized trace): requests, share, CV of inter-arrivals (azfn: CV of the per-minute counts, before and after
re-binning), plus the checks "CV change <= 10%" and "popularity order preserved". Caps on prompt/output are applied by
the generator (--max-prompt/--max-output) and reported in summary.json.
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workloads as w  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cv(ts):
    g = np.diff(np.sort(np.asarray(ts, float)))
    return float(g.std() / g.mean()) if len(g) > 1 and g.mean() > 0 else None


def count_cv(c):
    c = np.asarray(c, float)
    return float(c.std() / c.mean()) if c.mean() > 0 else None


def checks(before, after):
    order_b = sorted(before, key=lambda e: (-before[e]["requests"], e))
    order_a = sorted(after, key=lambda e: (-after[e]["requests"], e))
    dcv = {e: abs(after[e]["cv"] / before[e]["cv"] - 1) for e in before
           if before[e].get("cv") and after[e].get("cv")}
    return {"cv_change_max": max(dcv.values()) if dcv else None,
            "cv_ok": (max(dcv.values()) <= 0.10) if dcv else None,  # None: no arrival times in the source (T2)
            "popularity_order_ok": order_b == order_a}


def finish(a, rows, meta, before, after):
    rows.sort()
    meta.update({"source_sha256": sha256(a.src), "source_file": os.path.basename(a.src), "seed": 0,
                 "requests": len(rows), "span_s": a.span})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    w.write_trace(a.out, rows, meta)
    stats = {"meta": meta, "before": before, "after": after, "checks": checks(before, after)}
    json.dump(stats, open(a.out.replace(".csv.gz", "") + ".stats.json", "w"), indent=1)
    print(f"{a.out}: {len(rows)} requests, {len(after)} entities, checks {stats['checks']}")


def azfn(a):
    d = pd.read_csv(a.src)
    d = d[d.Trigger == "http"]
    cols = [str(m) for m in range(a.start_min + 1, a.start_min + a.window_min + 1)]
    counts = d[cols].to_numpy()
    tot = counts.sum(1)
    order = np.argsort(-tot, kind="stable")
    target = a.target_rate * a.span
    st = tot[order]

    def band(r0):  # n ranks log-spaced from r0 to the rank whose count is st[r0] / skew
        r1 = int(np.searchsorted(-st, -st[r0] / a.skew, side="right")) - 1
        if r1 - r0 + 1 < a.n:
            return None
        return np.unique(np.round(np.geomspace(r0 + 1, r1 + 1, a.n)).astype(int) - 1)

    best = None
    for r0 in range(len(st)):
        b = band(r0)
        if b is None or len(b) < a.n:
            continue
        err = abs(st[b].sum() - target)
        if best is None or err < best[0]:
            best = (err, r0, b)
        if st[b].sum() < target:
            break
    _, r0, ranks = best
    sel = order[ranks]
    tab = w.length_table("empirical:" + a.lengths)
    rng = np.random.default_rng(0)
    sec = a.span / a.window_min
    rows, before, after = [], {}, {}
    for k, i in enumerate(sel):
        e = f"fn{k + 1:02d}_{d.HashFunction.iloc[i][:8]}"
        c = counts[i]
        ts = np.concatenate([j * sec + rng.random(int(n)) * sec for j, n in enumerate(c)])
        for t in ts:
            p, o = tab[rng.integers(len(tab))]
            rows.append((float(t), e, int(p), int(o)))
        rebinned = np.bincount((ts // sec).astype(int), minlength=len(c))[:len(c)]
        before[e] = {"requests": int(c.sum()), "cv": count_cv(c), "cv_kind": "per-minute counts"}
        after[e] = {"requests": len(ts), "cv": count_cv(rebinned), "cv_kind": "per-minute counts (re-binned)",
                    "cv_interarrival": cv(ts)}
    total = sum(v["requests"] for v in after.values())
    for v in list(before.values()) + list(after.values()):
        v["share"] = v["requests"] / total
    meta = {"id": "T3", "source": "Azure Functions 2019 (AzurePublicDataset), day 1, HTTP trigger",
            "license": "CC-BY-4.0 (cite Shahrad et al., USENIX ATC 2020)",
            "rule": f"azfn: ranks {[int(r) + 1 for r in ranks]} of {len(order)} HTTP functions by invocations in minutes "
                    f"{a.start_min}-{a.start_min + a.window_min}; 1 min -> {sec:g} s; uniform within minute; "
                    f"lengths from {os.path.basename(a.lengths)}",
            "time_scale": sec / 60}
    finish(a, rows, meta, before, after)


def load_single(a):
    if a.kind == "azllm":
        d = pd.read_csv(a.src)
        t = pd.to_datetime(d.TIMESTAMP)
        return ((t - t.min()).dt.total_seconds().to_numpy(), d.ContextTokens.to_numpy(), d.GeneratedTokens.to_numpy(),
                {"id": "T4", "source": f"Azure LLM inference trace 2023 ({os.path.basename(a.src)})",
                 "license": "CC-BY-4.0 (cite Patel et al., Splitwise, ISCA 2024)"})
    d = pd.read_csv(a.src)
    model, log = a.filter.split("/")
    d = d[(d.Model == model) & (d["Log Type"] == log) & (d["Response tokens"] > 0)]
    rng = np.random.default_rng(0)
    t = d.Timestamp.to_numpy(float) + rng.random(len(d))
    return (t, d["Request tokens"].to_numpy(), d["Response tokens"].to_numpy(),
            {"id": "T5", "source": f"BurstGPT v1 ({os.path.basename(a.src)}), {a.filter}, failed (0 tokens) dropped, "
                                   "whole-second timestamps jittered U[0,1) s",
             "license": "CC-BY-4.0 (cite Wang et al., BurstGPT, 2024)"})


def window(a):
    t, pl, ol, meta = load_single(a)
    o = np.argsort(t, kind="stable")
    t, pl, ol = t[o], pl[o], ol[o]
    hours = np.bincount((t // 3600).astype(int))
    if a.anchor == "busiest":
        start = float(np.argmax(hours) * 3600)
    else:  # first hour whose following n x win s carry the target rate at time scale span / win (closest match)
        per_s = np.bincount(t.astype(int), minlength=int(t.max()) + 1)
        blk = int(a.n * a.win)
        csum = np.concatenate([[0], np.cumsum(per_s)])
        want = a.target_rate * a.span  # entities run in parallel over span s: target_rate x span requests in all
        win_s = int(a.win)
        cand = [(abs(csum[h * 3600 + blk] - csum[h * 3600] - want), h) for h in range(len(hours))
                if h * 3600 + blk < len(csum)
                and all(csum[h * 3600 + (k + 1) * win_s] > csum[h * 3600 + k * win_s] for k in range(a.n))]
        start = float(min(cand)[1] * 3600)
    scale = a.span / a.win
    rows, before, after = [], {}, {}
    for k in range(a.n):
        lo, hi = start + k * a.win, start + (k + 1) * a.win
        m = (t >= lo) & (t < hi)
        e = f"w{k + 1:02d}"
        ts = (t[m] - lo) * scale
        rows += [(float(x), e, int(p), int(q)) for x, p, q in zip(ts, pl[m], ol[m])]
        before[e] = {"requests": int(m.sum()), "cv": cv(t[m])}
        after[e] = {"requests": len(ts), "cv": cv(ts), "cv_interarrival": cv(ts)}
    total = sum(v["requests"] for v in after.values())
    for v in list(before.values()) + list(after.values()):
        v["share"] = v["requests"] / total
    meta.update({"rule": f"window: {a.n} consecutive {a.win:g}-s windows from t={start:.0f} s ({a.anchor} anchor), "
                         f"each stretched x{scale:g} to {a.span:g} s", "time_scale": scale})
    finish(a, rows, meta, before, after)


def lmsys(a):
    """T2: LMSYS-Chat-1M. Real popularity among the --n most frequent models; synthetic arrivals (the dataset has no
    times): each entity's count = round(share x target-rate x span) (shares within the top n, so the popularity is
    exactly the real one), placed as a Poisson process conditioned on that count (uniform order statistics, seed 0);
    lengths from the entity's own conversations: first user turn (prompt) and first assistant turn (output),
    tokenized with --tokenizer, from a seeded sample of up to --pool conversations per entity (empty answers dropped).
    The output is NOT redistributable (LMSYS-Chat-1M license): keep it out of the repository (.gitignore)."""
    import glob
    sys.path.insert(0, a.pqlib) if a.pqlib else None
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer

    files = sorted(glob.glob(os.path.join(a.src, "*.parquet")))
    counts = {}
    for f in files:
        for m in pq.read_table(f, columns=["model"]).column("model").to_pylist():
            counts[m] = counts.get(m, 0) + 1
    top = sorted(counts, key=lambda m: (-counts[m], m))[:a.n]
    tot_top = sum(counts[m] for m in top)
    rng = np.random.default_rng(0)
    pools = {m: [] for m in top}
    for f in files:
        t = pq.read_table(f, columns=["model", "conversation"]).to_pylist()
        for r in t:
            if r["model"] in pools:
                c = r["conversation"]
                if len(c) >= 2 and c[0]["role"] == "user" and c[1]["role"] == "assistant" and c[1]["content"].strip():
                    pools[r["model"]].append((c[0]["content"], c[1]["content"]))
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    lens = {}
    for m in top:
        pool = pools[m]
        idx = rng.choice(len(pool), size=min(a.pool, len(pool)), replace=False)
        ps = tok([pool[i][0] for i in idx], add_special_tokens=False)["input_ids"]
        os_ = tok([pool[i][1] for i in idx], add_special_tokens=False)["input_ids"]
        lens[m] = [(len(p), len(o)) for p, o in zip(ps, os_)]
    target = a.target_rate * a.span
    rows, before, after = [], {}, {}
    for k, m in enumerate(top):
        e = f"m{k + 1:02d}_{m}"
        n = int(round(counts[m] / tot_top * target))
        ts = np.sort(rng.random(n) * a.span)
        for t in ts:
            p, o = lens[m][rng.integers(len(lens[m]))]
            rows.append((float(t), e, max(1, p), max(1, o)))
        before[e] = {"requests": counts[m], "share": counts[m] / tot_top, "cv": None,
                     "prompt_p50": float(np.median([x[0] for x in lens[m]])),
                     "output_p50": float(np.median([x[1] for x in lens[m]]))}
        after[e] = {"requests": n, "share": n / max(1, round(target)), "cv": None, "cv_interarrival": cv(ts)}
    meta = {"id": "T2", "source": "LMSYS-Chat-1M (lmsys/lmsys-chat-1m, 6 parquet files)",
            "license": "LMSYS-Chat-1M Dataset License Agreement: NO redistribution; keep out of the repository",
            "rule": f"lmsys: top {a.n} of {len(counts)} models by conversations; counts = real share x "
                    f"{a.target_rate:g} req/s x {a.span:g} s; Poisson arrivals (synthetic); first-turn lengths, "
                    f"tokenizer {a.tokenizer}, pool {a.pool} conversations per model", "time_scale": 1}
    a.src = files[0]  # finish() hashes one file; the others are listed by name in the metadata
    meta["files"] = " ".join(os.path.basename(f) for f in files)
    finish(a, rows, meta, before, after)


def lengths(a):
    d = pd.read_csv(a.src)
    rows = [(0.0, "all", int(p), int(o)) for p, o in zip(d.ContextTokens, d.GeneratedTokens)]
    w.write_trace(a.out, rows, {"id": "L_azllm_conv", "source": os.path.basename(a.src), "source_sha256": sha256(a.src),
                                "license": "CC-BY-4.0 (cite Patel et al., Splitwise, ISCA 2024)",
                                "use": "length table for --lengths empirical:<file> (arrival unused)"})
    print(f"{a.out}: {len(rows)} (prompt, output) pairs")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("azfn")
    f.add_argument("--n", type=int, default=12)
    f.add_argument("--window-min", type=int, default=60)
    f.add_argument("--start-min", type=int, default=600)
    f.add_argument("--target-rate", type=float, default=2.0)
    f.add_argument("--skew", type=float, default=8.0)
    f.add_argument("--lengths", default=os.path.join(os.path.dirname(__file__), "traces", "L_azllm_conv.csv.gz"))
    g = sub.add_parser("window")
    g.add_argument("--kind", choices=["azllm", "burstgpt"], required=True)
    g.add_argument("--n", type=int, default=12)
    g.add_argument("--win", type=float, default=30)
    g.add_argument("--filter", default="ChatGPT/API log")
    g.add_argument("--anchor", choices=["busiest", "target"], default="busiest")
    g.add_argument("--target-rate", type=float, default=2.0)
    sub.add_parser("lengths")
    h = sub.add_parser("lmsys")
    h.add_argument("--n", type=int, default=12)
    h.add_argument("--target-rate", type=float, default=2.0)
    h.add_argument("--pool", type=int, default=5000)
    h.add_argument("--tokenizer", default="meta-llama/Llama-3.1-8B-Instruct")
    h.add_argument("--pqlib", default="", help="extra sys.path entry holding pyarrow (no env change)")
    for s in (f, g, h, sub.choices["lengths"]):
        s.add_argument("--src", required=True)
        s.add_argument("--out", required=True)
        s.add_argument("--span", type=float, default=600)
    a = p.parse_args()
    {"azfn": azfn, "window": window, "lengths": lengths, "lmsys": lmsys}[a.cmd](a)


if __name__ == "__main__":
    main()
