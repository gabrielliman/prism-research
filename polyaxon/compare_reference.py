"""Compare repeated configurations against reference repetitions (F0.4/F1.5 reproduction check, C-V3).

Usage: python3 polyaxon/compare_reference.py [--exclude-round R ...] <new metricas.csv> <reference metricas.csv> <new>=<ref> [...]

Each <new>/<ref> is <scenario>/<level>/<config> (summarize_reps.py's metricas.csv rows). For each pair and each
main metric, prints the reference mean and [min, max] over its repetitions, the new repetitions, and the
reproduction criterion decided at the F0 gate (reports/registro/decisoes.md, 2026-10-30): the 95% bootstrap
confidence interval of the difference of means (new − reference) must contain 0, for SLO, TTFT p90 and the worst
wait for the first token. The exact two-sided permutation p-value of the same difference is printed for
information. --exclude-round drops reference repetitions of that round, read from the manifest.csv next to the
reference metricas.csv (e.g. fix3, run on a degraded node). The ordering of configurations by SLO is checked on
both sides.
"""
import csv
import itertools
import os
import random
import sys
from statistics import mean

METRICS = [("SLO", 100, "%"), ("TTFT p90 (s)", 1, "s"), ("TTFT p99 (s)", 1, "s"),
           ("pior espera pelo 1º token (s)", 1, "s"), ("ativações", 1, ""), ("perdas", 1, "")]
CRITERION = {"SLO", "TTFT p90 (s)", "pior espera pelo 1º token (s)"}
BOOTSTRAP, SEED = 10000, 0


def load(path, exclude_rounds=()):
    rounds = {}
    manifest = os.path.join(os.path.dirname(path), "manifest.csv")
    if exclude_rounds and os.path.exists(manifest):
        for m in csv.DictReader(open(manifest)):
            rounds[(m["scenario"], m["config"], m["level"], "r" + m["rep"])] = m["round"]
    rows = {}
    for r in csv.DictReader(open(path)):
        if rounds.get((r["cenário"], r["config"], r["nível"], r["rep"])) in exclude_rounds:
            continue
        rows.setdefault(f"{r['cenário']}/{r['nível']}/{r['config']}", []).append(r)
    return rows


def values(rows, key, metric, scale):
    return [float(r[metric]) * scale for r in rows.get(key, []) if r.get(metric) not in (None, "")]


def bootstrap_ci(nv, rv, rng):
    """95% percentile interval of mean(new) − mean(ref), resampling each side independently."""
    diffs = sorted(mean(rng.choices(nv, k=len(nv))) - mean(rng.choices(rv, k=len(rv))) for _ in range(BOOTSTRAP))
    return diffs[int(0.025 * BOOTSTRAP)], diffs[int(0.975 * BOOTSTRAP) - 1]


def permutation_p(nv, rv):
    """Exact two-sided p-value of |mean(new) − mean(ref)| over all relabelings."""
    pooled, observed = nv + rv, abs(mean(nv) - mean(rv))
    splits = list(itertools.combinations(range(len(pooled)), len(nv)))
    hits = 0
    for idx in splits:
        a = [pooled[i] for i in idx]
        b = [pooled[i] for i in range(len(pooled)) if i not in idx]
        hits += abs(mean(a) - mean(b)) >= observed - 1e-9
    return hits / len(splits), len(splits)


def main():
    args, exclude = sys.argv[1:], []
    while args and args[0] == "--exclude-round":
        exclude.append(args[1])
        args = args[2:]
    new, ref = load(args[0]), load(args[1], exclude)
    pairs = [a.split("=", 1) for a in args[2:]]
    rng = random.Random(SEED)
    if exclude:
        print(f"Referência sem as rodadas: {', '.join(exclude)}")
    order_new, order_ref, failed = [], [], []
    for n, r in pairs:
        print(f"\n## {n}  (referência: {r}; {len(new.get(n, []))} novas, {len(ref.get(r, []))} de referência)")
        print("| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] "
              "| p permutação (rotulações) | critério |")
        print("| --- | --- | --- | --- | --- | --- |")
        for metric, scale, unit in METRICS:
            rv, nv = values(ref, r, metric, scale), values(new, n, metric, scale)
            if not rv or not nv:
                continue
            lo, hi = bootstrap_ci(nv, rv, rng)
            p, labelings = permutation_p(nv, rv)
            if metric in CRITERION:
                ok = lo <= 0 <= hi
                verdict = "OK" if ok else "FALHOU"
                if not ok:
                    failed.append(f"{n} {metric}")
            else:
                verdict = "(informativa)"
            print(f"| {metric} | {mean(rv):.1f} [{min(rv):.1f}, {max(rv):.1f}] | {mean(nv):.1f} "
                  f"({', '.join(f'{v:.1f}' for v in nv)}) | {mean(nv) - mean(rv):+.1f} [{lo:+.1f}, {hi:+.1f}] "
                  f"| {p:.2f} ({labelings}) | {verdict} |")
        order_new.append((mean(values(new, n, "SLO", 100) or [float("nan")]), n))
        order_ref.append((mean(values(ref, r, "SLO", 100) or [float("nan")]), r))
    by_level = {}
    for (sn, n), (sr, r) in zip(order_new, order_ref):
        by_level.setdefault(n.rsplit("/", 1)[0], []).append((sn, sr, n))
    for level, items in by_level.items():
        if len(items) > 1:
            same = sorted(items, key=lambda x: x[0]) == sorted(items, key=lambda x: x[1])
            print(f"\nOrdem por SLO em {level}: {'igual à referência' if same else 'DIFERENTE da referência'}")
    print(f"\nCritério de reprodução: {'OK' if not failed else 'FALHOU em ' + '; '.join(failed)}")


if __name__ == "__main__":
    main()
