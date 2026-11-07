"""GPU idleness (F5.0d, PLANO_AGENTE.md section 7, D32): how much of the GPU sits with models that are not serving.

Usage:
  python3 polyaxon/gpu_idle.py level <level dir>                     one level, JSON
  python3 polyaxon/gpu_idle.py table <data dir> <dest.csv>            every level of collect_reps.py's
                                                                      <scenario>/<config>/r<k>/<level>/ layout

Inputs of a level (extract_ovl.py): requests.csv, events.csv, gpu.csv, summary.json, ../config.json; the scenario (the
ovl_* part of the path) keys reports/registro/latencia_ded.json. Window: [0, T], T = the load's duration
(summary.json args.duration). Time is sampled every DT s. Per level:
  ocio_residente_demanda   GB·s of resident (active) models with no request in the system (arrived and not finished),
                           counted only at instants when some non-active model has a request in the system, over the
                           GPU's total GB·s (total_gb of gpu.csv × T). Memory that could be with whoever is waiting.
                           Weights only (model_info.json / slo_metrics.PROFILED), not KV.
  frac_tempo_demanda       fraction of the window with some non-active model holding requests.
  ocio_esperada            mean over the window of 1 − min(1, Σ_{m active at t} ρ_m), ρ_m = λ_m · E[S_m]: λ_m = the
                           model's arrivals in the window / T (the level's own load), E[S_m] = mean service time
                           (arrival → last token) of its identical models alone on a dedicated GPU
                           (pool_servico_medio_s, polyaxon/iso_dedicated.py). The idleness the load itself imposes.
  ocio_esperada_gpu        the same with E[S_m] = GPU-busy seconds per request on the dedicated GPU
                           (pool_gpu_s_por_req: nvidia-smi utilization integrated, over the answered requests), the
                           service time that accounts for batching; ρ_m = λ_m · E[S_m] with the end-to-end latency
                           counts every request of a batch as a full GPU, so Σρ passes 1 with two 8B models of C1 and
                           ocio_esperada is ~0 in every overloaded level (D44). ocio_politica_gpu = observed − this.
  ocio_observada           mean of 1 − util/100 of the nvidia-smi samples (gpu.csv) inside the window.
  ocio_politica            ocio_observada − ocio_esperada: idleness the load does not explain (positive = the policy
                           leaves the GPU idle; negative = the resident set works more than its dedicated load would,
                           e.g. a backlog).
  rho_total, rho_total_gpu  Σ_m ρ_m over every model, with each service time (the offered compute load); trocas_min = activations completed
                           (act_ok) per minute in the window.
A request is in the system from its arrival to arrival + latency; unserved and failed ones without a latency stay until
the end of the window. Model state comes from slo_metrics.state_at (active between act_ok and deact_ok).
"""
import csv
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import slo_metrics as sm  # noqa: E402

DT = 0.25  # s, time grid


def busy_mask(spans, grid):
    """bool array: grid points covered by any [start, end) span."""
    out = np.zeros(len(grid), dtype=bool)
    for a, b in spans:
        out |= (grid >= a) & (grid < b)
    return out


def active_mask(changes, grid):
    """bool array: grid points where the model is active (changes = slo_metrics.state_at list)."""
    out = np.zeros(len(grid), dtype=bool)
    for (t0, st), (t1, _) in zip(changes, changes[1:] + [(math.inf, None)]):
        if st == "active":
            out |= (grid >= t0) & (grid < t1)
    return out


def idleness(reqs, ev, cfg, gpu, T, rho, weights, total_gb, dt=DT, rho_gpu=None):
    """The metrics of the module docstring. rho, rho_gpu, weights: model -> ρ_m (NaN if unknown), GB."""
    grid = np.arange(0.0, T, dt)
    states = sm.state_at(ev, cfg)
    models = [m["model_name"] for m in cfg]
    spans = {m: [] for m in models}
    for r in reqs:
        lat = r.get("latency", math.nan)
        spans[r["model"]].append((r["arrival"], r["arrival"] + lat if not math.isnan(lat) else math.inf))
    busy = {m: busy_mask(spans[m], grid) for m in models}
    act = {m: active_mask(states[m], grid) for m in models}
    pending = np.zeros(len(grid), dtype=bool)
    for m in models:
        pending |= busy[m] & ~act[m]
    idle_gb = sum(weights[m] * (act[m] & ~busy[m]) for m in models)
    expected = lambda r: float(np.mean(1 - np.minimum(1.0, sum(np.where(act[m], r[m], 0.0) for m in models))))
    util = [1 - float(g["util"]) / 100 for g in gpu if 0 <= float(g["t"]) < T and g["util"] != ""]
    esperada = expected(rho) if len(grid) else math.nan
    esp_gpu = expected(rho_gpu) if rho_gpu is not None and len(grid) else math.nan
    observada = float(np.mean(util)) if util else math.nan
    acts = sum(1 for e in ev if e["kind"] == "act_ok" and 0 <= float(e["t"]) < T)
    return {"janela_s": T, "ocio_residente_demanda": float((idle_gb * pending).sum() * dt / (total_gb * T)),
            "frac_tempo_demanda": float(pending.mean()) if len(grid) else math.nan,
            "ocio_esperada": esperada, "ocio_observada": observada, "ocio_politica": observada - esperada,
            "ocio_esperada_gpu": esp_gpu, "ocio_politica_gpu": observada - esp_gpu,
            "rho_total": float(sum(rho.values())),
            "rho_total_gpu": float(sum(rho_gpu.values())) if rho_gpu is not None else math.nan,
            "trocas_min": acts / (T / 60)}


def level(d, refs):
    d = pathlib.Path(d)
    reqs, ev, cfg = sm.load_level(d)
    gpu = list(csv.DictReader(open(d / "gpu.csv")))
    s = json.load(open(d / "summary.json"))
    T = float(s["args"].get("duration") or max(r["arrival"] for r in reqs))
    scenario = sm.ded_scenario(d)
    path = {m["model_name"]: m["model_path"] for m in cfg}
    rho, rho_gpu = {}, {}
    for m, p in path.items():
        e = refs.ded_entry(scenario, m, p) or {}
        lam = sum(1 for r in reqs if r["model"] == m and r["arrival"] < T) / T
        es, eg = e.get("pool_servico_medio_s"), e.get("pool_gpu_s_por_req")
        rho[m] = lam * es if es is not None else math.nan
        rho_gpu[m] = lam * eg if eg is not None else math.nan
    total = float(gpu[0]["total_gb"]) if gpu else math.nan
    return idleness(reqs, ev, cfg, gpu, T, rho, {m: refs.weights[p] for m, p in path.items()}, total, rho_gpu=rho_gpu)


def table(data, dest, refs):
    rows = []
    for d, (scenario, config, rep, lvl) in sm.levels(data):
        rows.append({"cenário": scenario, "config": config, "nível": lvl, "rep": rep, **level(d, refs)})
    sm.write(dest, rows)
    print(f"{dest}: {len(rows)} levels")


def main():
    refs = sm.Refs()
    if sys.argv[1] == "level":
        print(json.dumps(level(sys.argv[2], refs), indent=1))
    elif sys.argv[1] == "table":
        table(sys.argv[2], sys.argv[3], refs)


if __name__ == "__main__":
    main()
