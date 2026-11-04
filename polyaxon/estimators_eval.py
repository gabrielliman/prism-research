"""Offline evaluation of the arrival-rate estimator λ̂_m (F2.5) on the arrivals of existing loads.

Usage: python3 polyaxon/estimators_eval.py rate <dest.md> <name>=<level dir> [...] [--horizons 5 15 30]
       python3 polyaxon/estimators_eval.py queue <dest.md> <latencia_ref.json> <name>=<level dir> [...]

For each load (requests.csv: model, arrival) and each model, at every whole second t of the window, the estimator
fed with the arrivals up to t predicts the number of arrivals in (t, t + H]; that is compared with the real count.
Per load and horizon, over all (model, t): mean absolute error (MAE), MAE normalized by the mean real count, and
the Brier score of P(at least one arrival in H) = 1 − e^(−λ̂H) (Poisson). Baselines: the model's real mean rate
over the window (clairvoyant constant rate: what is left is Poisson noise plus the load's changes of rate), the count
of the last H seconds (naive), each window alone, and the combination with burst detection only (no lull detection). Grid: short τ ∈ {5, 10, 20} s, long τ ∈ {30, 60, 120} s, burst ratio ∈
{1.5, 2, 3}; the table lists the naive baseline, each window alone at the default τ, the default combination (10 s,
60 s, 2) and the best grid point per load and horizon (in-sample: it shows how much tuning could gain, not a choice).
"""
import bisect
import csv
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python", "sglang",
                                "multi_model", "scheduling"))
import estimators as est  # noqa: E402

SHORTS, LONGS, RATIOS = (5.0, 10.0, 20.0), (30.0, 60.0, 120.0), (1.5, 2.0, 3.0)
DEFAULT = (10.0, 60.0, 2.0)


def arrivals(level):
    per = {}
    for r in csv.DictReader(open(os.path.join(level, "requests.csv"))):
        per.setdefault(r["model"], []).append(float(r["arrival"]))
    dur = max(max(v) for v in per.values())
    return {m: sorted(v) for m, v in per.items()}, dur


def predictions(times, dur, H, make, mode):
    """[(predicted count, real count)] at t = 1, 2, ... while t + H ≤ dur."""
    out = []
    e = make()
    i = 0
    t = 1.0
    while t + H <= dur:
        while i < len(times) and times[i] <= t:
            e.arrival(times[i])
            i += 1
        real = bisect.bisect_right(times, t + H) - bisect.bisect_right(times, t)
        if mode == "mean":  # clairvoyant constant rate: the model's real mean rate over the whole window
            rate = len(times) / dur
            pred = rate * H
        elif mode == "naive":
            pred = bisect.bisect_right(times, t) - bisect.bisect_right(times, t - H)
            rate = pred / H
        else:
            short, long_ = e.rates(t)
            if mode == "upward":  # burst detection only (symmetric=False)
                rate = short if short > e.burst_ratio * long_ else long_
            else:
                rate = {"short": short, "long": long_, "combined": e.rate(t)}[mode]
            pred = rate * H
        out.append((pred, real, 1 - math.exp(-rate * H)))
        t += 1.0
    return out


def score(pairs):
    n = len(pairs)
    mae = sum(abs(p - r) for p, r, _ in pairs) / n
    mean = sum(r for _, r, _ in pairs) / n
    brier = sum((q - (r > 0)) ** 2 for _, r, q in pairs) / n
    return mae, mae / mean if mean else math.nan, brier


def evaluate(level, H, params, mode):
    per, dur = arrivals(level)
    s, l, ratio = params
    pairs = []
    for times in per.values():
        pairs += predictions(times, dur, H, lambda: est.RateEstimator(s, l, ratio, start=0.0), mode)
    return score(pairs)


def queue_eval(dest, ref_path, loads):
    """Time to first token predicted at arrival, for served requests that arrived while their model was active (D14
    states) with requests ahead of them: prefill sum (queue_time + prefill_time), observed first-token rate of the
    model in the last 30 s, and the hybrid of estimators.queue_time_hybrid (decision D17). Error vs the real TTFT."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import json
    import slo_metrics as sm
    ref = json.load(open(ref_path))
    q = lambda xs, k: sorted(xs)[int(k * (len(xs) - 1))] if xs else float("nan")
    lines = ["# q̂_r: TTFT previsto na chegada × real (gerado por `polyaxon/estimators_eval.py queue`)", "",
             "Requisições atendidas que chegaram com o modelo ativo e com requisições na frente (do mesmo modelo, chegadas "
             "antes e ainda sem 1º token). Erro absoluto do TTFT previsto (q̂ + p̂), em segundos, p50 / p90.", "",
             "| Carga | n | sem fila na frente | TTFT real p50 / p90 | soma dos prefills | taxa observada (30 s) | híbrido (≥ 10 na janela) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, level in loads:
        reqs, ev, cfg = sm.load_level(level)
        path = {m["model_name"]: m["model_path"] for m in cfg}
        states = sm.state_at(ev, cfg)
        per = {}
        for r in reqs:
            per.setdefault(r["model"], []).append(r)
        res = {"sum": [], "tput": [], "hyb": []}
        real, total, empty = [], 0, 0
        for m, rs in per.items():
            coef = ref[path[m]]
            first = sorted(r["arrival"] + r["ttft"] for r in rs if r["status"] == "ok")
            rs.sort(key=lambda r: r["arrival"])
            for i, r in enumerate(rs):
                if r["status"] != "ok" or sm.lookup(states[m], r["arrival"]) != "active":
                    continue
                total += 1
                a = r["arrival"]
                ahead = [x["prompt_len"] for x in rs[:i] if x["status"] != "ok" or x["arrival"] + x["ttft"] > a]
                if not ahead:
                    empty += 1
                    continue
                done = bisect.bisect_right(first, a) - bisect.bisect_left(first, a - 30)
                s_ = est.queue_time(ahead, coef) + est.prefill_time(r["prompt_len"], coef)
                t_ = (len(ahead) + 1) / (done / 30) if done else 60.0
                h_ = est.queue_time_hybrid(ahead, r["prompt_len"], coef, done)
                real.append(r["ttft"])
                for k, v in (("sum", s_), ("tput", t_), ("hyb", h_)):
                    res[k].append(abs(v - r["ttft"]))
        f = lambda xs: f"{q(xs, .5):.2f} / {q(xs, .9):.2f}"
        lines.append(f"| {name} | {len(real)} | {empty / total:.0%} | {f(real)} | {f(res['sum'])} | {f(res['tput'])} | {f(res['hyb'])} |")
        print(lines[-1], flush=True)
    open(dest, "w").write("\n".join(lines) + "\n")


def main():
    if sys.argv[1] == "queue":
        queue_eval(sys.argv[2], sys.argv[3], [a.split("=", 1) for a in sys.argv[4:]])
        return
    args = sys.argv[2:]
    horizons = [5.0, 15.0, 30.0]
    if "--horizons" in args:
        i = args.index("--horizons")
        horizons = [float(x) for x in args[i + 1:]]
        args = args[:i]
    dest, loads = args[0], [a.split("=", 1) for a in args[1:]]
    lines = ["# λ̂_m: erro de previsão de chegadas no horizonte H (gerado por `polyaxon/estimators_eval.py`)", "",
             "MAE em requisições por modelo e janela; MAE normalizado = MAE / média real; Brier de P(≥ 1 chegada em H). "
             "Padrão = (τ curta 10 s, τ longa 60 s, razão de rajada 2). Melhor da grade é dentro da amostra.", "",
             "| Carga | H (s) | taxa média real (clarividente) | ingênuo (últimos H s) | só curta (10 s) | só longa (60 s) "
             "| padrão, só subida | padrão (subida e queda) | melhor da grade (τc, τl, razão) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    fmt = lambda x: f"{x[0]:.2f} / {x[1]:.0%} / {x[2]:.3f}"
    for name, level in loads:
        for H in horizons:
            mean = evaluate(level, H, DEFAULT, "mean")
            naive = evaluate(level, H, DEFAULT, "naive")
            up = evaluate(level, H, DEFAULT, "upward")
            short = evaluate(level, H, DEFAULT, "short")
            long_ = evaluate(level, H, DEFAULT, "long")
            comb = evaluate(level, H, DEFAULT, "combined")
            best = min(((evaluate(level, H, p, "combined"), p) for p in itertools.product(SHORTS, LONGS, RATIOS)),
                       key=lambda x: x[0][0])
            lines.append(f"| {name} | {H:.0f} | {fmt(mean)} | {fmt(naive)} | {fmt(short)} | {fmt(long_)} | {fmt(up)} | {fmt(comb)} | "
                         f"{fmt(best[0])} ({best[1][0]:.0f}, {best[1][1]:.0f}, {best[1][2]:g}) |")
            print(lines[-1], flush=True)
    lines += ["", "Cada célula: MAE / MAE normalizado / Brier."]
    open(dest, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
