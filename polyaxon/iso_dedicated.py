"""SLO base of each model from its own workload on a dedicated GPU (F2.10, the Prism paper's §7.1; decision D20).

Usage: python3 polyaxon/iso_dedicated.py <dest dir> <job outputs dir> [...]
       each outputs dir holds <suite line>/<step>/<level>_ded_<model>/ (run_examples.sh PRISM_OVL_DEDICATED)

Per (scenario, model of the scenario): the model's requests of the scenario's reference level, sent alone to a server
with only that model, resident (overload_load.py --only-model). TTFT and TPOT as in every run (server timestamps,
benchmark.py). Per model: P50 and P95 of the TTFT and of the TPOT of its answered requests. The base (D21) pools the
answered requests of all models of the scenario with the same model_path (identical models): pool_ttft_p95,
pool_tpot_p95 (S2) and pool_ttft_p50, pool_tpot_p50 (S2M), copied into each model's entry. Writes
<dest>/latencia_ded.json ({scenario: {model: {model_path, ttft_p95, tpot_p95, ttft_p50, tpot_p50, pool_*, pool_models,
pool_n, n, ok, unserved, failed, level}}}, what slo_metrics.py reads as reports/registro/latencia_ded.json) and
<dest>/latencia_ded.md.
"""
import glob
import json
import os
import re
import sys

import numpy as np

LEVEL = re.compile(r"^(?P<level>.+)_ded_(?P<model>model_\d+)$")


def main():
    dest, roots = sys.argv[1], sys.argv[2:]
    os.makedirs(dest, exist_ok=True)
    ref, rows, samples = {}, [], {}
    for root in roots:
        for s in sorted(glob.glob(os.path.join(root, "*", "ovl_*", "*_ded_model_*", "summary.json"))):
            d = os.path.dirname(s)
            step, lvl = d.split(os.sep)[-2], d.split(os.sep)[-1]
            m = LEVEL.match(lvl)
            reqs = json.load(open(os.path.join(d, "requests.json")))
            ok = [r for r in reqs if r["status"] == "ok"]
            ttft = np.array([r["ttft"] for r in ok])
            tpot = np.array([r["tpot"] for r in ok if r["tpot"] > 0])
            cfg = glob.glob(os.path.join(os.path.dirname(os.path.dirname(d)), "configs", f"{step}_ded.json"))
            path = json.load(open(cfg[0]))[0]["model_path"] if cfg else ""
            # the config file is rewritten per model: the path of this level is in its server log's model config
            log = os.path.join(d, "server_file.log")
            if os.path.exists(log):
                pm = re.search(r"meta-llama/[A-Za-z0-9.\-]+", open(log, errors="replace").read(200000))
                path = pm.group(0) if pm else path
            e = {"model_path": path, "level": m.group("level"), "n": len(reqs), "ok": len(ok),
                 "unserved": sum(r["status"] == "unserved" for r in reqs),
                 "failed": sum(r["status"] == "failed" for r in reqs),
                 "ttft_p95": float(np.quantile(ttft, 0.95)) if len(ttft) else None,
                 "tpot_p95": float(np.quantile(tpot, 0.95)) if len(tpot) else None,
                 "ttft_p50": float(np.median(ttft)) if len(ttft) else None,
                 "tpot_p50": float(np.median(tpot)) if len(tpot) else None}
            ref.setdefault(step, {})[m.group("model")] = e
            pool = samples.setdefault((step, path), ([], []))
            pool[0].extend(ttft)
            pool[1].extend(tpot)
            rows.append((step, m.group("model"), e))
    pooled = {}
    for (step, path), (tt, tp) in samples.items():
        tt, tp = np.array(tt), np.array(tp)
        pooled[step, path] = {"pool_ttft_p95": float(np.quantile(tt, 0.95)), "pool_tpot_p95": float(np.quantile(tp, 0.95)),
                              "pool_ttft_p50": float(np.median(tt)), "pool_tpot_p50": float(np.median(tp)),
                              "pool_models": sum(e["model_path"] == path for e in ref[step].values()),
                              "pool_n": len(tt)}
    for step in ref:
        for e in ref[step].values():
            e.update(pooled[step, e["model_path"]])
    json.dump(ref, open(os.path.join(dest, "latencia_ded.json"), "w"), indent=1)
    fmt = lambda x, k: f"{x * k:.1f}" if x is not None else "—"
    lines = ["# Base do SLO por modelo, carga própria em GPU dedicada (gerado por `polyaxon/iso_dedicated.py`)", "",
             "| Carga | Nível | Modelo | Caminho | Requisições (ok / não atendidas / falhas) | TTFT p50 / **p95** (ms) | "
             "TPOT p50 / **p95** (ms) |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for step, model, e in sorted(rows, key=lambda x: (x[0], int(x[1].split("_")[1]))):
        lines.append(f"| {step} | {e['level']} | {model} | {e['model_path'].split('/')[-1]} | {e['n']} ({e['ok']} / "
                     f"{e['unserved']} / {e['failed']}) | {fmt(e['ttft_p50'], 1000)} / **{fmt(e['ttft_p95'], 1000)}** | "
                     f"{fmt(e['tpot_p50'], 1000)} / **{fmt(e['tpot_p95'], 1000)}** |")
    lines += ["", "## Base do SLO (D21): requisições dos modelos idênticos da carga juntas", "",
              "| Carga | Caminho | Modelos | Requisições atendidas | TTFT p50 / **p95** (ms) | TPOT p50 / **p95** (ms) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for (step, path), e in sorted(pooled.items()):
        lines.append(f"| {step} | {path.split('/')[-1]} | {e['pool_models']} | {e['pool_n']} | "
                     f"{fmt(e['pool_ttft_p50'], 1000)} / **{fmt(e['pool_ttft_p95'], 1000)}** | "
                     f"{fmt(e['pool_tpot_p50'], 1000)} / **{fmt(e['pool_tpot_p95'], 1000)}** |")
    lines += ["", "## Dispersão entre modelos idênticos (por que a base junta as requisições, D21)", ""]
    for step in sorted(ref):
        for path in sorted({e["model_path"] for e in ref[step].values()}):
            es = [e for e in ref[step].values() if e["model_path"] == path and e["ttft_p95"] is not None]
            if len(es) > 1:
                for q in ("p95", "p50"):
                    tt, tp = [e[f"ttft_{q}"] for e in es], [e[f"tpot_{q}"] for e in es]
                    lines.append(f"- {step}, {path.split('/')[-1]} ({len(es)} modelos), {q}: TTFT de {min(tt) * 1000:.1f} "
                                 f"a {max(tt) * 1000:.1f} ms (CV {np.std(tt) / np.mean(tt):.1%}); TPOT de "
                                 f"{min(tp) * 1000:.1f} a {max(tp) * 1000:.1f} ms (CV {np.std(tp) / np.mean(tp):.1%})")
    open(os.path.join(dest, "latencia_ded.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
