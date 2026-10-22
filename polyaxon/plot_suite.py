"""Timelines and a metrics table for every level extracted by extract_ovl.py under a data directory.

Usage: python3 polyaxon/plot_suite.py <data dir> <figure dir>

For each <data dir>/.../<step>/<level>/ (a directory with summary.json) writes
<figure dir>/<path with "/" -> "__">.png (ovl_plots.linha_do_tempo) and appends a row to
<figure dir>/metricas.csv (ovl_plots.metricas, plus the path components).
Needs pandas and matplotlib.
"""
import os
import pathlib
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ovl_plots as op  # noqa: E402


def main():
    data, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for summary in sorted(data.rglob("summary.json")):
        d = summary.parent
        rel = d.relative_to(data)
        lv = op.nivel(d)
        name = "__".join(rel.parts)
        op.linha_do_tempo(lv, " · ".join(rel.parts), out=out / f"{name}.png", fases=op.fases_por_modelo(lv))
        rows.append({"execução": str(rel), **op.metricas(lv)})
        print(f"{rel}: {out / name}.png")
    pd.DataFrame(rows).to_csv(out / "metricas.csv", index=False)


if __name__ == "__main__":
    main()
