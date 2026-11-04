"""Statistics and content hash of the workload one level sent (F2.7, catalogue in reports/registro/cargas.md).

Usage: python3 polyaxon/workload_stats.py <level dir with requests.csv or requests.json> [--md]

The workload is what the generator built, so it depends only on the arguments and the seed, not on the server:
the hash covers (id, model, arrival, prompt_len, output_len) of every request, so two levels with the same hash
sent the same requests. Prints JSON (or a Markdown block with --md): duration, requests, total and per-model
rate, CV of the per-model inter-arrivals, popularity (share of requests per model, in decreasing order) and
prompt/output length quantiles. No numpy needed.
"""
import csv
import hashlib
import json
import os
import statistics
import sys


def load(level):
    p = os.path.join(level, "requests.csv")
    if os.path.exists(p):
        rows = list(csv.DictReader(open(p)))
    else:
        rows = json.load(open(os.path.join(level, "requests.json")))
    reqs = [(str(r["id"]), r["model"], float(r["arrival"]), int(r["prompt_len"]), int(r["output_len"])) for r in rows]
    return sorted(reqs, key=lambda r: (r[2], int(r[0])))


def quantiles(xs, qs=(0.1, 0.5, 0.9, 0.99)):
    s = sorted(xs)
    return {f"p{int(q * 100)}": s[min(len(s) - 1, int(q * len(s)))] for q in qs}


def cv(times):
    gaps = [b - a for a, b in zip(times, times[1:])]
    if len(gaps) < 2 or statistics.mean(gaps) == 0:
        return None
    return statistics.pstdev(gaps) / statistics.mean(gaps)


def stats(level):
    reqs = load(level)
    summ = os.path.join(level, "summary.json")
    dur = json.load(open(summ))["args"]["duration"] if os.path.exists(summ) else max(r[2] for r in reqs)
    h = hashlib.sha256("\n".join(f"{i},{m},{a:.3f},{p},{o}" for i, m, a, p, o in reqs).encode()).hexdigest()
    per = {}
    for _, m, a, _, _ in reqs:
        per.setdefault(m, []).append(a)
    n = len(reqs)
    models = sorted(per, key=lambda m: (-len(per[m]), m))
    return {
        "level": level, "sha256": h, "duration_s": dur, "requests": n, "rate_total": n / dur,
        "per_model": {m: {"requests": len(per[m]), "rate": len(per[m]) / dur, "share": len(per[m]) / n,
                          "cv_interarrival": cv(per[m])} for m in models},
        "cv_interarrival_total": cv([r[2] for r in reqs]),
        "prompt_len": quantiles([r[3] for r in reqs]), "output_len": quantiles([r[4] for r in reqs]),
    }


def md(s):
    pm = s["per_model"]
    cvs = [v["cv_interarrival"] for v in pm.values() if v["cv_interarrival"] is not None]
    lines = [f"- Nível de referência: `{s['level']}`",
             f"- Hash (sha256 de id, modelo, chegada, prompt, saída): `{s['sha256'][:16]}…`",
             f"- {s['requests']} requisições em {s['duration_s']:.0f} s ({s['rate_total']:.3f} req/s), {len(pm)} modelos",
             f"- CV entre chegadas por modelo: mediana {statistics.median(cvs):.2f} (mín {min(cvs):.2f}, máx {max(cvs):.2f})" if cvs else "- CV: n/d",
             "- Popularidade (fração das requisições): " + ", ".join(f"{m} {v['share']:.1%}" for m, v in pm.items()),
             "- Prompt (tokens): " + ", ".join(f"{k} {v}" for k, v in s["prompt_len"].items()),
             "- Saída (tokens, exata): " + ", ".join(f"{k} {v}" for k, v in s["output_len"].items())]
    return "\n".join(lines)


def main():
    s = stats(sys.argv[1])
    print(md(s) if "--md" in sys.argv else json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
