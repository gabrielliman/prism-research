#!/usr/bin/env python3
"""F4 report figures: timelines (GPU memory / controller free memory / per-model state and responses) of the same
job with and without A1, from the levels f4_analysis.py extracted.

Usage: /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f4_figs.py [<campaign dir>] [<figs dir>]
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ovl_plots as op  # noqa: E402

CAMP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "reports/data/F04/campanha")
FIGS = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "reports/figs/F04")
NOMES = {"A0.1": "original (A0.1), sem A1", "A0.1_A1": "original (A0.1) + A1",
         "A0.3": "troca por throughput (A0.3), sem A1", "A0.3_A1": "troca por throughput (A0.3) + A1"}
CASOS = [  # (job, step, level, configs, title prefix)
    ("f4-c6-1", "ovl_zipf", "rate2", ["A0.1", "A0.1_A1"], "C6 Zipf com tamanhos reais"),
    ("f4-c1n8-1", "ovl_mem", "rate0.2", ["A0.1", "A0.1_A1"], "C1 com 8 modelos"),
    ("f4-c1n14-1", "ovl_mem", "rate0.2", ["A0.1_A1"], "C1 com 14 modelos"),
    ("f4-t3-1", "ovl_tr_azfn", "ts1", ["A0.3", "A0.3_A1"], "T3 Azure Functions"),
]


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    for job, step, lvl, cfgs, titulo in CASOS:
        for cfg in cfgs:
            d = CAMP / "levels" / job / cfg / step / lvl
            if not d.exists():
                print("missing", d)
                continue
            lv = op.nivel(d)
            out = FIGS / f"{job}_{cfg}.png"
            op.linha_do_tempo(lv, f"{titulo} — {NOMES[cfg]} ({job})", out=str(out))
            print(out)


if __name__ == "__main__":
    main()
