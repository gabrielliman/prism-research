import random, sys
import pandas as pd
D = sys.argv[1].rstrip("/") + "/"
n = pd.read_csv(D + "niveis.csv")
j = pd.read_csv(D + "justica.csv")
m = n.merge(j, on=["job", "config"], suffixes=("", "_j"))


def boot(v, k=10000):
    r = random.Random(1)
    means = sorted(sum(r.choice(v) for _ in v) / len(v) for _ in range(k))
    return sum(v) / len(v), means[int(0.025 * k)], means[int(0.975 * k) - 1]


def cell(vals, scale):
    mu, lo, hi = boot([x * scale for x in vals])
    return f"{mu:+6.1f} [{lo:+6.1f},{hi:+6.1f}]{'*' if lo * hi > 0 else ' '}"


ARMS = [("lvfp", "S3k5", "ps"), ("lvfp", "S6k1", "ps"), ("pred", "S3k5", "p0"), ("pred", "S6k1", "p0"),
        ("loss", "S6k4", "p0"), ("value", "S6k4", "p0")]
for ref in ("A0.4", "lvfr"):
    print(f"\n=== arm − {ref} at the arm's level (pooled 8 jobs, 95% CI): total pts | worst quarter pts | Jain x100 | worst-model p90 s | max wait s")
    for p, lv, tag in ARMS:
        a = m[m.config == f"{p}_{lv}_{tag}"].set_index("job")
        b = m[m.config == (ref if ref == "A0.4" else f"lvfr_{lv}_p0")].set_index("job")
        jobs = a.index.intersection(b.index)
        d = lambda col: [a.loc[x, col] - b.loc[x, col] for x in jobs]
        print(f"  {p:5s} {lv}: {cell(d(f'{lv}_so_ttft'), 100)} | {cell(d(f'{lv}_quartil_ttft'), 100)} | "
              f"{cell(d(f'{lv}_jain_ttft'), 100)} | {cell(d(f'{lv}_pior_p90_s'), 1)} | {cell(d('espera_max'), 1)}")
