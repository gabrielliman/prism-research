"""Activation and deactivation costs from the server logs, and the activation-cost estimator Ĉ_at (F2.3).

Usage:
  python3 polyaxon/activation_cost.py extract <dest.csv> <round>=<downloads dir> [...]
  python3 polyaxon/activation_cost.py fit <activations.csv> <dest dir>

extract: for every level <dl>/<job>/outputs/<config>/ovl_*/<level>/ that passes collect_reps.clean, one row per
  activation and per deactivation seen by the GPU scheduler ("Received activate request for model X" ->
  "Model X (instance N) activation succeeded"; "Received deactivate request for X" -> "deactivation succeeded"):
    round job config step level kind model weights_gb t (s from the level's first log line) dur_s
    ahead      other activations already in flight when this one was requested (the model service loads one
               model at a time, P10, so they are served first)
    inflight   other activations in flight at any point of this one
    free_gb    free GPU memory the controller last logged before the request ("GPU 0, mem X")
    deact_inflight  deactivations in flight when it was requested (their memory is still being released)
    worker_s   the worker's own cost line ("Activate model ... time cost" / "Deactivate time cost"), nearest match
  Writes <dest.csv> with kind = activate | deactivate.

fit: Ĉ_at(m) = a + b·W_m + c·ahead (median regression), fitted on the even-numbered jobs of each round and evaluated on
  the odd ones (and the reverse), so the error is out-of-sample. Writes <dest>/cat_model.json (coefficients, fitted
  on all rows) and <dest>/cat_fit.md (error table, quantiles of the cost by model size and by `ahead`, deactivation
  quantiles including the P11 tail). Needs pandas/numpy (/mnt/scratch/scheduler/opt-env/bin/python).
"""
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_reps  # noqa: E402
import extract_ovl as ex  # noqa: E402

ACT_REQ = re.compile(r"Received activate request for model (model_\d+)$")
ACT_OK = re.compile(r"Model (model_\d+) \(instance \d+\) activation succeeded")
DEACT_REQ = re.compile(r"Received deactivate request for (model_\d+),")
DEACT_OK = re.compile(r"Model (model_\d+) \(instance \d+\) deactivation succeeded")
FREE = re.compile(r"GPU 0, mem ([0-9.]+)")
W_ACT = re.compile(r"Activate model (model_\d+) \(.*\) time cost: ([0-9.]+)s")
W_DEACT = re.compile(r"Worker \d+ \((model_\d+)\) TP=0\] Deactivate time cost: ([0-9.]+)s")
COLS = ["round", "job", "config", "step", "level", "kind", "model", "weights_gb", "t", "dur_s", "ahead", "inflight",
        "free_gb", "deact_inflight", "worker_s"]


def weights(cfg_dir, step):
    info = json.load(open(os.path.join(os.path.dirname(collect_reps.__file__), "..", "python", "sglang",
                                       "multi_model", "utils", "model_info.json")))
    info.setdefault("meta-llama/Llama-3.1-8B-Instruct", {"model_size": 14.95755871385336})  # profiled at run time
    cfg = json.load(open(os.path.join(cfg_dir, "configs", f"{step}.json")))
    return {m["model_name"]: info[m["model_path"]]["model_size"] for m in cfg}


def level_rows(level, meta, w):
    gs = list(ex.log_lines(os.path.join(level, "server_file.log.gpu_scheduler.log")))
    if not gs:
        return []
    t0 = gs[0][0]
    free = [(ts, float(m.group(1))) for ts, line in ex.log_lines(os.path.join(level, "server_file.log.global_controller.log"))
            if (m := FREE.search(line))]
    wcost = {"activate": [], "deactivate": []}
    for ts, line in ex.log_lines(os.path.join(level, "server_file.log")):
        if m := W_ACT.search(line):
            wcost["activate"].append((ts, m.group(1), float(m.group(2))))
        elif m := W_DEACT.search(line):
            wcost["deactivate"].append((ts, m.group(1), float(m.group(2))))
    spans = {"activate": [], "deactivate": []}  # (model, start, end)
    open_ = {"activate": {}, "deactivate": {}}
    for ts, line in gs:
        line = line.rstrip()
        for kind, rq, ok in (("activate", ACT_REQ, ACT_OK), ("deactivate", DEACT_REQ, DEACT_OK)):
            if m := rq.search(line):
                open_[kind].setdefault(m.group(1), ts)
            elif m := ok.search(line):
                if (start := open_[kind].pop(m.group(1), None)) is not None:
                    spans[kind].append((m.group(1), start, ts))
    rows = []
    for kind, ss in spans.items():
        for model, start, end in ss:
            others = [s for s in spans["activate"] if s[0] != model or s[1] != start]
            fr = [v for ts, v in free if ts <= start]
            wc = [c for ts, m, c in wcost[kind] if m == model and start - 1 <= ts <= end + 1]
            rows.append({**meta, "kind": kind, "model": model, "weights_gb": round(w.get(model, 0), 3),
                         "t": round(start - t0, 3), "dur_s": round(end - start, 3),
                         "ahead": sum(s[1] < start < s[2] for s in others),
                         "inflight": sum(s[1] < end and s[2] > start for s in others),
                         "free_gb": round(fr[-1], 2) if fr else "",
                         "deact_inflight": sum(s[1] < start < s[2] for s in spans["deactivate"] if s[0] != model),
                         "worker_s": wc[0] if wc else ""})
    return rows


def extract(dest, rounds):
    rows = []
    for round_, root in rounds:
        for job_dir in sorted(glob.glob(os.path.join(root, "*"))):
            for s in sorted(glob.glob(os.path.join(job_dir, "outputs", "*", "ovl_*", "*", "summary.json"))):
                level = os.path.dirname(s)
                step_dir = os.path.dirname(level)
                cfg_dir = os.path.dirname(step_dir)
                if not collect_reps.clean(level):
                    continue
                meta = {"round": round_, "job": os.path.basename(job_dir), "config": os.path.basename(cfg_dir),
                        "step": os.path.basename(step_dir), "level": os.path.basename(level)}
                try:
                    w = weights(cfg_dir, meta["step"])
                except (FileNotFoundError, KeyError):
                    w = {}
                rows += level_rows(level, meta, w)
    with open(dest, "w", newline="") as f:
        wr = csv.DictWriter(f, COLS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"{dest}: {sum(r['kind'] == 'activate' for r in rows)} activations, "
          f"{sum(r['kind'] == 'deactivate' for r in rows)} deactivations")


def fit(src, dest):
    import numpy as np
    import pandas as pd

    df = pd.read_csv(src)
    act = df[(df.kind == "activate") & (df.weights_gb > 0)].copy()
    dea = df[df.kind == "deactivate"].copy()
    act["run"] = act["round"] + "/" + act.job
    jobs = sorted(act.run.unique())
    act["fold"] = act.run.map({j: i % 2 for i, j in enumerate(jobs)})

    def design(d):
        return np.column_stack([np.ones(len(d)), d.weights_gb, d.ahead])

    def solve(d):
        # Median (L1) regression by iteratively reweighted least squares: the cost has a heavy tail (P11 stalls,
        # node slowdowns), so least squares fits the mean, ~40% above the typical activation.
        X, y = design(d), d.dur_s.values
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        for _ in range(100):
            w = 1 / np.maximum(np.abs(y - X @ coef), 1e-3)
            coef = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        return coef

    act["pred"] = np.nan
    for k in (0, 1):
        coef = solve(act[act.fold != k])
        act.loc[act.fold == k, "pred"] = design(act[act.fold == k]) @ coef
    act["rel_err"] = (act.pred - act.dur_s).abs() / act.dur_s
    coef = solve(act)
    os.makedirs(dest, exist_ok=True)
    model = {"formula": "C_at = a + b*weights_gb + c*ahead (median regression)", "a": coef[0], "b": coef[1], "c": coef[2],
             "rows": len(act), "jobs": len(jobs), "median_rel_err_out_of_sample": float(act.rel_err.median()),
             "p90_rel_err_out_of_sample": float(act.rel_err.quantile(0.9)),
             "per_weights_gb": {str(w): {"n": int(len(g)), "p50": float(g.dur_s.median()), "p90": float(g.dur_s.quantile(0.9)),
                                         "p99": float(g.dur_s.quantile(0.99)), "max": float(g.dur_s.max()),
                                         "p50_ahead0": float(g[g.ahead == 0].dur_s.median()) if (g.ahead == 0).any() else None}
                                for w, g in act.groupby("weights_gb")}}
    json.dump(model, open(os.path.join(dest, "cat_model.json"), "w"), indent=1)

    def q(s):
        return f"{len(s)} | {s.median():.2f} | {s.quantile(0.9):.2f} | {s.quantile(0.99):.2f} | {s.max():.2f}"

    lines = [f"# Ĉ_at: custo de ativação e de desativação (gerado por `polyaxon/activation_cost.py fit {src}`)", "",
             f"Modelo: `Ĉ_at = {coef[0]:.3f} + {coef[1]:.4f}·W_GB + {coef[2]:.3f}·ahead` (s), ajustado pela mediana (regressão L1) em {len(act)} ativações "
             f"de {len(jobs)} jobs. `ahead` = ativações já em andamento no pedido (o model service carrega um modelo por vez).", "",
             f"Erro relativo fora da amostra (ajuste nos jobs pares, avaliação nos ímpares e vice-versa): "
             f"mediana {act.rel_err.median():.1%}, p90 {act.rel_err.quantile(0.9):.1%}.", "",
             "## Ativação (pedido → sucesso no GPU scheduler), s", "",
             "| Grupo | n | p50 | p90 | p99 | máx |", "| --- | --- | --- | --- | --- | --- |"]
    for w, g in act.groupby("weights_gb"):
        lines.append(f"| W = {w:.1f} GB | {q(g.dur_s)} |")
        for a, ga in g.groupby(g.ahead.clip(upper=4)):
            lines.append(f"| W = {w:.1f} GB, ahead = {a}{'+' if a == 4 else ''} | {q(ga.dur_s)} |")
    lines += ["", "Erro relativo fora da amostra por grupo:", "", "| Grupo | n | mediana | p90 |", "| --- | --- | --- | --- |"]
    for (w, a), g in act.groupby(["weights_gb", act.ahead.clip(upper=4)]):
        lines.append(f"| W = {w:.1f} GB, ahead = {a} | {len(g)} | {g.rel_err.median():.1%} | {g.rel_err.quantile(0.9):.1%} |")
    lines += ["", "## Ativação por memória livre vista pelo controlador (ahead = 0), s", "",
              "| Memória livre | n | p50 | p90 | p99 | máx |", "| --- | --- | --- | --- | --- | --- |"]
    a0 = act[act.ahead == 0].dropna(subset=["free_gb"])
    for b, g in a0.groupby(pd.cut(a0.free_gb, [0, 20, 40, 80, 200])):
        if len(g):
            lines.append(f"| {b} GB | {q(g.dur_s)} |")
    # With drain (throughput swap D1: A0.3/A0.4) the GPU scheduler's span includes up to PRISM_SWAP_DRAIN_TIMEOUT s of
    # draining; the worker's own cost line (code from F1.7 on) is the memory release alone, where the P11 tail lives.
    dea["drain"] = dea.config.str.contains(r"D1|A0\.[34]")
    rel = dea.dropna(subset=["worker_s"])
    lines += ["", "## Desativação, s", "",
              "Pedido → sucesso no GPU scheduler (inclui a drenagem nas variantes com drenagem) e, quando o log tem a linha "
              "de custo do worker (código a partir da F1.7), só a liberação de memória no worker, onde está a cauda da P11.", "",
              "| Grupo | n | p50 | p90 | p99 | máx |", "| --- | --- | --- | --- | --- | --- |",
              f"| GPU scheduler, sem drenagem | {q(dea[~dea.drain].dur_s)} |",
              f"| GPU scheduler, com drenagem | {q(dea[dea.drain].dur_s)} |",
              f"| liberação no worker (todas) | {q(rel.worker_s)} |"]
    for r, g in rel.groupby("round"):
        lines.append(f"| liberação no worker, rodada {r} | {q(g.worker_s)} |")
    lines += ["", f"Liberação no worker > 5 s: {(rel.worker_s > 5).sum()} de {len(rel)}; > 10 s: {(rel.worker_s > 10).sum()}."]
    model["deactivation_release_s"] = {"n": int(len(rel)), "p50": float(rel.worker_s.median()),
                                       "p90": float(rel.worker_s.quantile(0.9)), "p99": float(rel.worker_s.quantile(0.99)),
                                       "max": float(rel.worker_s.max())}
    json.dump(model, open(os.path.join(dest, "cat_model.json"), "w"), indent=1)
    open(os.path.join(dest, "cat_fit.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    cmd, *args = sys.argv[1:]
    if cmd == "extract":
        extract(args[0], [a.split("=", 1) for a in args[1:]])
    else:
        fit(*args)


if __name__ == "__main__":
    main()
