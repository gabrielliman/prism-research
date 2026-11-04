"""Campaign checks C-V1–C-V3 (PLANO_AGENTE.md section 3.2) over a collect_reps.py/summarize_reps.py data directory.

Usage: python3 polyaxon/validate_campaign.py <data dir> <validator.csv> [--min-reps N] [--cv-max F]
                                             [--pair <new>=<ref> ...]

<data dir> holds metricas.csv and manifest.csv; <validator.csv> is validate_run.py --csv over the downloads the data
came from (joined on the job uuid and the level path <job>/outputs/<config>/<step>/<level>, the manifest's source). Only VALIDA levels count; the others are listed with their reason.
  C-V1  valid repetitions per configuration (scenario, config, level) ≥ --min-reps (default 5)
  C-V2  coefficient of variation of the SLO attainment across the valid repetitions ≤ --cv-max (default 0.15);
        the CV of TTFT p90 and of the worst wait for the first token is printed for information
  C-V3  for each --pair <scenario>/<level>/<config>=<scenario>/<level>/<config> (the reference run in the same period,
        decision D8): the 95% bootstrap CI of mean(new) − mean(ref) contains 0 for SLO, TTFT p90 and the worst wait
        (decision D2; compare_reference.bootstrap_ci, same seed and resamples)
Prints a Markdown report; exit status 1 when a check fails.
"""
import csv
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_reference as cr  # noqa: E402

MAIN = [("SLO", 100), ("TTFT p90 (s)", 1), ("pior espera pelo 1º token (s)", 1)]


def cv(xs):
    """nan with fewer than 2 values, a zero mean or a non-finite value (a model never served: infinite wait)."""
    if len(xs) < 2 or not all(math.isfinite(x) for x in xs) or statistics.mean(xs) == 0:
        return float("nan")
    return statistics.pstdev(xs) / statistics.mean(xs)


def main():
    args = sys.argv[1:]
    opts = {"--min-reps": 5, "--cv-max": 0.15}
    pairs = []
    for flag in list(opts) + ["--pair"]:
        while flag in args:
            i = args.index(flag)
            if flag == "--pair":
                pairs.append(args[i + 1].split("=", 1))
            else:
                opts[flag] = float(args[i + 1])
            del args[i:i + 2]
    data, vcsv = args
    status = {}
    for r in csv.DictReader(open(vcsv)):
        status[(r["uuid"], r["source"])] = (r["status"], r["motivo"])
    manifest = {(m["scenario"], m["config"], m["level"], "r" + m["rep"]): m for m in csv.DictReader(open(os.path.join(data, "manifest.csv")))}
    groups, invalid, unknown = {}, [], []
    for r in csv.DictReader(open(os.path.join(data, "metricas.csv"))):
        k = (r["cenário"], r["config"], r["nível"], r["rep"])
        m = manifest.get(k)
        st = status.get((m["uuid"], m["source"])) if m else None
        if st is None:
            unknown.append("/".join(k))
            continue
        if st[0] != "VALIDA":
            invalid.append(("/".join(k), st[0], st[1][:150]))
            continue
        groups.setdefault(f"{r['cenário']}/{r['nível']}/{r['config']}", []).append(r)
    failed = []
    print(f"# Verificações de campanha: {data}\n")
    print(f"Níveis válidos: {sum(map(len, groups.values()))}; inválidos: {len(invalid)}; sem veredito do validador: {len(unknown)}\n")
    print(f"| configuração | repetições válidas | C-V1 (≥ {opts['--min-reps']:.0f}) | CV do SLO | C-V2 (≤ {opts['--cv-max']:.0%}) "
          f"| CV TTFT p90 | CV pior espera |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for key, rows in sorted(groups.items()):
        n = len(rows)
        cvs = [cv([float(r[mt]) * sc for r in rows]) for mt, sc in MAIN]
        v1 = n >= opts["--min-reps"]
        v2 = cvs[0] <= opts["--cv-max"]  # nan (one repetition, or a non-finite SLO) fails
        failed += [f"C-V1 {key}"] * (not v1) + [f"C-V2 {key}"] * (not v2)
        print(f"| {key} | {n} | {'OK' if v1 else 'FALHA'} | {cvs[0]:.1%} | {'OK' if v2 else 'FALHA'} | {cvs[1]:.1%} | {cvs[2]:.1%} |")
    if pairs:
        rng = random.Random(cr.SEED)
        print("\n## C-V3: diferença para a referência do mesmo período (IC 95% bootstrap)\n")
        print("| nova | referência | métrica | nova − referência [IC 95%] | C-V3 |")
        print("| --- | --- | --- | --- | --- |")
        for new, ref in pairs:
            for mt, sc in MAIN:
                nv = [float(r[mt]) * sc for r in groups.get(new, [])]
                rv = [float(r[mt]) * sc for r in groups.get(ref, [])]
                if not nv or not rv:
                    print(f"| {new} | {ref} | {mt} | sem repetições válidas | FALHA |")
                    failed.append(f"C-V3 {new}")
                    continue
                lo, hi = cr.bootstrap_ci(nv, rv, rng)
                ok = lo <= 0 <= hi
                failed += [f"C-V3 {new} {mt}"] * (not ok)
                print(f"| {new} | {ref} | {mt} | {statistics.mean(nv) - statistics.mean(rv):+.2f} [{lo:+.2f}, {hi:+.2f}] | {'OK' if ok else 'FALHA'} |")
    if invalid:
        print("\n## Níveis inválidos (fora dos agregados)\n")
        for k, st, why in invalid:
            print(f"- `{k}`: {st} — {why}")
    if unknown:
        print(f"\nSem veredito (fora dos agregados): {', '.join(unknown[:20])}{' …' if len(unknown) > 20 else ''}")
    print(f"\n**Resultado:** {'OK' if not failed else 'FALHA (' + str(len(failed)) + '): ' + '; '.join(failed[:12])}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
