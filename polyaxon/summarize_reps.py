"""Per-level metrics and per-configuration summary of a collect_reps.py data directory.

Usage: python3 polyaxon/summarize_reps.py <data dir>

Writes <data dir>/metricas.csv (one row per level: ovl_plots.metricas plus scenario, config, level, rep) and
<data dir>/resumo.csv (one row per scenario, config and level: number of repetitions, then the mean, min and
max of each metric). Needs pandas.
"""
import os
import pathlib
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ovl_plots as op  # noqa: E402


def main():
    data = pathlib.Path(sys.argv[1])
    rows = []
    for summary in sorted(data.rglob("summary.json")):
        d = summary.parent
        scenario, config, rep, level = d.relative_to(data).parts
        m = op.metricas(op.nivel(d))
        m["% atendidas"] = 100 * m["atendidas"] / m["enviadas"]
        m["perdas"] = m["não atendidas"] + m["falhas"]
        rows.append({"cenário": scenario, "config": config, "nível": level, "rep": rep, **m})
    df = pd.DataFrame(rows)
    df.to_csv(data / "metricas.csv", index=False)
    keys = ["cenário", "config", "nível"]
    num = df.drop(columns=keys + ["rep"]).select_dtypes("number").columns
    g = df.groupby(keys)
    out = g.size().rename("n").to_frame()
    for stat in ("mean", "min", "max"):
        out = out.join(g[num].agg(stat).add_suffix(f" {stat}"))
    out.reset_index().to_csv(data / "resumo.csv", index=False)
    print(f"{len(df)} levels, {len(out)} configurations")


if __name__ == "__main__":
    main()
