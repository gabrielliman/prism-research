"""Timeline around the freeze of one level: events (activations, retracts, evictions) with times, and per-model
last completion and pending count, plus the GPU memory/util at the freeze."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, "polyaxon")
import extract_ovl as ex  # noqa: E402

d = sys.argv[1]
reqs = json.load(open(f"{d}/requests.json"))
t0 = ex.load_start(d, reqs)
ev = ex.events(d, t0)
for e in ev:
    if e[2] not in ("no_fit", "free_mem"):
        print(f"  t={e[0]:7.1f} {e[1]:>9} {e[2]} {e[3:] if len(e) > 3 else ''}")
ok = [r for r in reqs if r["status"] == "ok"]
last = max(r["arrival"] + r["latency"] for r in ok)
print(f"last completion t={last:.0f}")
for m in sorted({r["model"] for r in reqs}, key=lambda s: int(s.split("_")[1])):
    mo = [r for r in ok if r["model"] == m]
    print(f"  {m}: ok {len(mo)}, unserved {sum(r['model'] == m and r['status'] != 'ok' for r in reqs)}, "
          f"last done {max((r['arrival'] + r['latency'] for r in mo), default=None)}")
gpu = ex.gpu_rows(os.path.join(d, "gpu.csv"), t0)
for g in gpu:
    if abs(g[0] - (last + 60)) < 1 or abs(g[0] - (last + 200)) < 1:
        print(f"  gpu t={g[0]:.0f}: used {g[1]:.1f}/{g[2]:.1f} GB util {g[3]}%")
