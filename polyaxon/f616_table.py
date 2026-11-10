"""F6.16 summary: per deadline level, total TTFT-only within deadline, worst quarter of models, Jain, worst-model p90,
max wait, rotations; mean over jobs in the analysis dir. Usage: f616_table.py <analysis dir>"""
import sys
import pandas as pd
D = sys.argv[1].rstrip("/") + "/"
n = pd.read_csv(D + "niveis.csv")
j = pd.read_csv(D + "justica.csv")
NAME = {"A0.2_A1": "idle eviction 10 s", "A0.4": "throughput swap", "lvfr": "VLT residency (ref.)",
        "lvfp": "A9.4 VLT per-swap preempt", "pred": "A2.3 predictive", "loss": "A3.1 expected loss",
        "value": "A10.1 value"}
LV = {"S3k5": "tight ~7 s", "S6k1": "one swap ~16 s", "S6k4": "four swaps ~63 s"}
print(f"jobs: {n.job.nunique()}")
for lv in LV:
    rows = []
    for c in ["A0.2_A1", "A0.4"] + sorted(x for x in n.config.unique() if f"_{lv}_" in x):
        x, y = n[n.config == c], j[j.config == c]
        if x.empty:
            continue
        key = c if c in NAME else c.split("_")[0]
        rows.append({"policy": NAME[key], "total %": 100 * x[f"{lv}_so_ttft"].mean(),
                     "worst quarter %": 100 * y[f"{lv}_quartil_ttft"].mean(), "worst model %": 100 * y[f"{lv}_pior_ttft"].mean(),
                     "Jain": y[f"{lv}_jain_ttft"].mean(), "worst-model p90 s": y[f"{lv}_pior_p90_s"].mean(),
                     "max wait s": x["espera_max"].mean(), "TTFT p50/p90 s": f"{x.ttft_p50.mean():.0f}/{x.ttft_p90.mean():.0f}",
                     "rotations": x["rotacoes"].mean()})
    t = pd.DataFrame(rows).set_index("policy")
    print(f"\n=== {LV[lv]}")
    print(t.round({"total %": 0, "worst quarter %": 0, "worst model %": 0, "Jain": 3, "worst-model p90 s": 0,
                   "max wait s": 0, "rotations": 0}).to_string())
