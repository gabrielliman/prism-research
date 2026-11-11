"""F6.15 violation decomposition (F6 acceptance criterion; PLANO_AGENTE.md section 7, D32): TTFT misses split into
unavoidable (inev_ativacao: the model fit but the deadline < Ĉ_at; inev_rotacao: it did not fit and the deadline <
Ĉ_rot) and avoidable (evit_residencia: only a decision before the arrival would have met it; evit: the rest), plus
unserved and TPOT misses during a model transition, each as a fraction of all sent requests (slo_metrics.evaluate).

Usage: f615_decomp.py <analysis dir>   (after f60_analysis.py; reads <dir>/niveis.csv and <dir>/levels/...)
Writes <dir>/decomposicao.csv (one row per job x config x level) and prints the means over jobs per level.
Each arm is scored at its own deadline level; the baselines A0.2_A1 and A0.4 at every level.
"""
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slo_metrics as sm  # noqa: E402
from f60_analysis import LEVELS  # noqa: E402

D = pathlib.Path(sys.argv[1])
n = pd.read_csv(D / "niveis.csv")
refs = sm.Refs()
G = ["viol_ttft_inev_ativacao", "viol_ttft_inev_rotacao", "viol_ttft_evit_residencia", "viol_ttft_evit",
     "viol_tpot_em_troca"]
rows = []
for r in n.itertuples():
    d = D / "levels" / r.job / r.config / getattr(r, "cenário") / getattr(r, "nível")
    reqs, ev, conf = sm.load_level(d)
    sc = sm.ded_scenario(d)
    own = [lv for lv in LEVELS if f"_{lv}_" in r.config] or list(LEVELS)  # baselines: every level
    for lv in own:
        m = sm.evaluate(reqs, ev, conf, LEVELS[lv], refs, False, sc)
        rows.append({"job": r.job, "carga": r.carga, "config": r.config, "nivel": lv, "so_ttft": m["so_ttft"],
                     "nao_atendidas": m["nao_atendidas"], **{g: m.get(g) for g in G}})
t = pd.DataFrame(rows)
t.to_csv(D / "decomposicao.csv", index=False)
pd.set_option("display.width", 200)
s = t.groupby(["nivel", "config"])[["so_ttft"] + G].mean().mul(100).round(1)
print("% of all sent requests, mean over jobs (inev = unavoidable, evit = avoidable)")
print(s.to_string())
