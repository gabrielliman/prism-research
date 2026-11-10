"""F6.15 confirmation (D54): per-policy tables and paired differences with 95% bootstrap CIs.

Usage: f615_compare.py <analysis dir> [--boot 10000]
Reads niveis.csv and justica.csv written by f60_analysis.py / f60_fairness.py; writes tabela_politicas.csv and
pareado.csv into the analysis dir and prints both.

Arms (per deadline level lv in S3k5, S6k1, S6k2, S6k4): lvfr_<lv>_p0 (A9.2 residency-aware VLT, no preemption),
edf_<lv>_p0 (A2.1 EDF), lvfp_<lv>_ps (A9.4, per-swap preemption, lambda 1) and, at S6k4 only, edf_S6k4_p1 (A2.1 with
preemption). Baselines A0.2_A1 (idle eviction 10 s) and A0.4 (throughput swap) have no deadline of their own; they are
scored at every level. Each arm is compared with A0.4, A0.2_A1 and A9.2 (lvfr) at the same level, paired by job.
Pooled CI: stratified bootstrap (reps resampled within each workload, the 4x5 design kept); per workload: the 5 reps.
"""
import sys
import numpy as np
import pandas as pd

D = sys.argv[1].rstrip("/") + "/"
B = int(sys.argv[sys.argv.index("--boot") + 1]) if "--boot" in sys.argv else 10000
n = pd.read_csv(D + "niveis.csv")
j = pd.read_csv(D + "justica.csv")
m = n.merge(j, on=["job", "config"], suffixes=("", "_j"))
LEVELS = ["S3k5", "S6k1", "S6k2", "S6k4"]
NAME = {"A0.2_A1": "A0.2+A1 idle eviction 10 s", "A0.4": "A0.4 throughput swap", "lvfr": "A9.2 VLT residency",
        "edf": "A2.1 EDF", "lvfp": "A9.4 VLT per-swap preempt (lambda 1)", "edf_p1": "A2.1 EDF + preemption"}


def arms(lv):
    a = [("lvfr", f"lvfr_{lv}_p0"), ("edf", f"edf_{lv}_p0"), ("lvfp", f"lvfp_{lv}_ps")]
    return a + ([("edf_p1", "edf_S6k4_p1")] if lv == "S6k4" else [])


def metrics(lv):  # (column, label, scale)
    return [(f"{lv}_so_ttft", "total %", 100), (f"{lv}_comb", "total comb %", 100),
            (f"{lv}_quartil_ttft", "worst quarter %", 100), (f"{lv}_pior_ttft", "worst model %", 100),
            (f"{lv}_jain_ttft", "Jain x100", 100), (f"{lv}_pior_p90_s", "worst-model p90 s", 1),
            ("ttft_p50", "TTFT p50 s", 1), ("ttft_p90", "TTFT p90 s", 1), ("espera_p99", "wait p99 s", 1),
            ("espera_max", "max wait s", 1), ("rotacoes", "rotations", 1), ("preemptadas", "preempted", 1)]


rng = np.random.default_rng(1)


def boot(df):
    """df: rows = jobs with columns carga, d. Stratified bootstrap of the mean over workloads."""
    groups = [g.d.to_numpy() for _, g in df.groupby("carga")]
    tot = sum(len(g) for g in groups)
    s = np.zeros(B)
    for g in groups:
        s += g[rng.integers(0, len(g), (B, len(g)))].sum(1)
    s /= tot
    return df.d.mean(), np.quantile(s, 0.025), np.quantile(s, 0.975)


# ---- per-policy table: mean over jobs, pooled and per workload
rows = []
for lv in LEVELS:
    for key, cfg in [("A0.2_A1", "A0.2_A1"), ("A0.4", "A0.4")] + arms(lv):
        x = m[m.config == cfg]
        for carga, g in [("todas", x)] + list(x.groupby("carga")):
            if g.empty:
                continue
            r = {"nivel": lv, "carga": carga, "politica": NAME[key], "jobs": len(g)}
            for col, lab, sc in metrics(lv):
                r[lab] = sc * g[col].mean()
            rows.append(r)
t = pd.DataFrame(rows)
t.to_csv(D + "tabela_politicas.csv", index=False)

# ---- paired differences arm - ref at the arm's level
rows = []
for lv in LEVELS:
    for key, cfg in arms(lv):
        for ref, rcfg in [("A0.4", "A0.4"), ("A0.2_A1", "A0.2_A1"), ("lvfr", f"lvfr_{lv}_p0")]:
            if rcfg == cfg:
                continue
            a = m[m.config == cfg].set_index("job")
            b = m[m.config == rcfg].set_index("job")
            jobs = a.index.intersection(b.index)
            for col, lab, sc in metrics(lv):
                df = pd.DataFrame({"carga": a.loc[jobs, "carga"], "d": sc * (a.loc[jobs, col] - b.loc[jobs, col])})
                for carga, g in [("todas", df)] + list(df.groupby("carga")):
                    mu, lo, hi = boot(g)
                    rows.append({"nivel": lv, "braco": NAME[key], "ref": NAME[ref], "carga": carga, "metrica": lab,
                                 "jobs": len(g), "media": mu, "ic_lo": lo, "ic_hi": hi,
                                 "sig": bool(lo > 0 or hi < 0), "braco_media": sc * a.loc[g.index, col].mean(),
                                 "ref_media": sc * b.loc[g.index, col].mean()})
p = pd.DataFrame(rows)
p.to_csv(D + "pareado.csv", index=False)

# ---- print
pd.set_option("display.width", 250)
SHOW = ["total %", "worst quarter %", "worst model %", "Jain x100", "worst-model p90 s", "TTFT p50 s", "TTFT p90 s",
        "wait p99 s", "max wait s", "rotations", "preempted"]
print(f"jobs: {m.job.nunique()} ({', '.join(f'{c} {k}' for c, k in m.groupby('carga').job.nunique().items())})")
for lv in LEVELS:
    x = t[(t.nivel == lv) & (t.carga == "todas")].set_index("politica")[SHOW]
    print(f"\n=== {lv}: mean over jobs\n{x.round(1).to_string()}")
KEY = ["total %", "worst quarter %", "Jain x100", "worst-model p90 s", "TTFT p90 s", "max wait s"]
for carga in ["todas"] + sorted(set(p.carga) - {"todas"}):
    print(f"\n##### paired arm - ref, {carga} (95% CI, * = excludes 0)")
    for lv in LEVELS:
        print(f"--- {lv}")
        q = p[(p.nivel == lv) & (p.carga == carga) & p.metrica.isin(KEY)]
        for (braco, ref), g in q.groupby(["braco", "ref"], sort=False):
            g = g.set_index("metrica").loc[KEY]
            cells = " | ".join(f"{r.media:+6.1f} [{r.ic_lo:+6.1f},{r.ic_hi:+6.1f}]{'*' if r.sig else ' '}"
                               for r in g.itertuples())
            print(f"  {braco[:28]:28s} - {ref[:14]:14s}: {cells}")
print("\ncolumns: " + " | ".join(KEY))
