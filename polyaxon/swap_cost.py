#!/usr/bin/env python3
"""F5.0a (D32): the real cost of a model rotation, decomposed, from the controller and GPU-scheduler logs.

Usage:
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/swap_cost.py <dest dir> <validator.csv> [...]

Only levels the validator classified VALIDA are used (section 0.2). Each validator row names a raw level directory
(root + level: <job>/outputs/<config>/<step>/<level>, with server_file.log.*), extracted to <dest>/levels/ first
(extract_ovl.extract_level).

A rotation is a controller decision that evicts busy or idle models FOR a waiting model X (events evict_swap,
evict_edf, evict_lvf, evict_fair, evict_pressure, evict_deadlock; the evictions of one cycle for the same X form one
rotation). For each rotation, at decision time t_d:
  t_out    the last victim's deactivation completed (deact_ok)                     -> exit   = t_out − t_d
  t_act    the controller decided to activate X (ACTION activate), after t_out     -> cycle  = t_act − t_out
           (the wait for a controller cycle that sees the freed memory; negative if X was activated before the
           victims left, i.e. it fit anyway)
  t_req    the GPU scheduler received the activation request                       -> queue  = t_req − t_act
  t_ready  X's activation succeeded (act_ok)                                       -> load   = t_ready − t_req
  C_rot  = t_ready − t_d (decision -> X ready), the cost a deadline policy pays for a rotation
Outcomes: ok; lapsed (no activation of X within LAPSE_S of the decision: the reservation expired or X lost the
memory); victim_stuck (a victim never left). Exit mode: preempt (P1), drain (PRISM_SWAP_DRAIN, before D30) or
finish (P0, no drain), from the level's decision log (preempt / drain_timeout of the action) or its config name.
The activation cost the policies estimate (Ĉ_at, F2.3: a + b·weights + c·activations ahead) is computed for X at
t_d with the activations pending then, for comparison (ratio C_rot / Ĉ_at).

Writes:
  <dest>/rotacoes.csv   one row per rotation: level, policy, mode, X, weights_gb, victims, times, outcome, Ĉ_at
  <dest>/resumo.md      per (mode, model size): n, outcomes, p50/p90 of exit, cycle, queue, load and C_rot,
                        and C_rot / Ĉ_at; the per-size medians are Ĉ_rot(m) (S6 base, F5.0b)
  <dest>/c_rot.json     {mode: {weights_gb (rounded): {"n", "p50", "p90"}}} for slo_metrics.py (S6)
"""
import csv
import glob
import json
import math
import os
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_ovl  # noqa: E402
import slo_metrics as sm  # noqa: E402

ROT_KINDS = {"evict_swap", "evict_edf", "evict_lvf", "evict_fair", "evict_pressure", "evict_deadlock"}
LAPSE_S = 120.0
SAME_CYCLE_S = 1.0
CAT = json.load(open(HERE.parent / "reports" / "data" / "F02" / "cat" / "cat_model.json"))


def c_at(weights_gb, ahead):
    return CAT["a"] + CAT["b"] * weights_gb + CAT.get("c", 0.0) * ahead


def extracted(lvl, dest):
    if (lvl / "events.csv").exists():
        return lvl
    rel = pathlib.Path(*lvl.parts[-5:]) if len(lvl.parts) >= 5 else pathlib.Path(lvl.name)
    out = dest / "levels" / rel
    if not (out / "events.csv").exists():
        extract_ovl.extract_level(str(lvl), str(out))
    if not (out.parent / "config.json").exists():
        cfg = lvl.parents[1] / "configs" / f"{lvl.parent.name}.json"
        if cfg.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.parent.joinpath("config.json").write_text(cfg.read_text())
    return out


def exit_mode(raw, cfg_name):
    """preempt / drain / finish, from the decision log's deactivate actions (rotations only), else the config name."""
    dl = pathlib.Path(raw) / "decisions.jsonl"
    if dl.exists():
        for line in open(dl, errors="replace"):
            for a in json.loads(line).get("actions", []):
                if a.get("kind") == "deactivate" and " for " in a.get("reason", "") \
                        and not a["reason"].startswith("deadlock"):
                    if a.get("drain_timeout"):
                        return "drain"
                    return "preempt" if a.get("preempt") else "finish"
    n = cfg_name.lower()
    if "d1" in n:
        return "drain"
    return "preempt" if ("p1" in n or n.endswith("p")) else "finish"


def pending_at(ev, t):
    """Activations requested and not yet completed at time t (the 'ahead' of Ĉ_at)."""
    open_ = set()
    for e in ev:
        if e["t"] > t:
            break
        if e["kind"] == "act_req":
            open_.add(e["model"])
        elif e["kind"] in ("act_ok", "model_lost"):
            open_.discard(e["model"])
    return len(open_)


def rotations(lvl, raw, refs):
    ev = [dict(e, t=float(e["t"])) for e in csv.DictReader(open(lvl / "events.csv"))]
    ev.sort(key=lambda e: e["t"])
    cfg = json.load(open(lvl.parent / "config.json")) if (lvl.parent / "config.json").exists() else []
    path = {m["model_name"]: m["model_path"] for m in cfg}
    cfg_name = lvl.parts[-3]
    mode = exit_mode(raw, cfg_name)
    decs = [e for e in ev if e["kind"] in ROT_KINDS and e["value"]]
    out, seen = [], set()
    for d in decs:
        key = (d["value"], round(d["t"]))
        if key in seen:
            continue
        x, td = d["value"], d["t"]
        victims = [e["model"] for e in decs if e["value"] == x and abs(e["t"] - td) <= SAME_CYCLE_S]
        seen |= {(x, round(e["t"])) for e in decs if e["value"] == x and abs(e["t"] - td) <= SAME_CYCLE_S}
        outs = []
        for v in victims:
            t = next((e["t"] for e in ev if e["t"] >= td and e["model"] == v
                      and e["kind"] in ("deact_ok", "stale_deact", "model_lost")), None)
            outs.append(t)
        t_out = None if None in outs else max(outs)
        t_act = next((e["t"] for e in ev if e["t"] >= td and e["kind"] == "activate" and e["model"] == x), None)
        t_req = next((e["t"] for e in ev if t_act is not None and e["t"] >= t_act and e["kind"] == "act_req"
                      and e["model"] == x), None)
        t_ready = next((e["t"] for e in ev if t_req is not None and e["t"] >= t_req and e["kind"] == "act_ok"
                        and e["model"] == x), None)
        if t_out is None:
            outcome = "victim_stuck"
        elif t_act is None or t_act - td > LAPSE_S or t_ready is None:
            outcome = "lapsed"
        else:
            outcome = "ok"
        w = refs.weights.get(path.get(x, ""), math.nan)
        cat = c_at(w, pending_at(ev, td)) if not math.isnan(w) else math.nan
        diff = lambda a, b: round(a - b, 3) if a is not None and b is not None else None
        # the A1.2 detector always preempts its victim, whatever the level's swap mode
        out.append({"nivel": str(lvl), "config": cfg_name, "modo": "preempt" if d["kind"] == "evict_deadlock" else mode,
                    "tipo": d["kind"], "modelo": x,
                    "pesos_gb": round(w, 1) if not math.isnan(w) else None, "vitimas": " ".join(victims),
                    "t_decisao": td, "saida": diff(t_out, td), "ciclo": diff(t_act, t_out), "fila": diff(t_req, t_act),
                    "carga": diff(t_ready, t_req), "c_rot": diff(t_ready, td) if outcome == "ok" else None,
                    "c_at": round(cat, 3) if not math.isnan(cat) else None, "resultado": outcome})
    return out


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return sm.pct(xs, q) if xs else math.nan


def f(x):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.1f}".replace(".", ",")


def main():
    dest = pathlib.Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    refs = sm.Refs(cat="/nonexistent")
    rows, used, dropped = [], 0, 0
    raws = []
    for vcsv in sys.argv[2:]:
        for v in csv.DictReader(open(vcsv)):
            if v["status"] != "VALIDA":
                dropped += 1
                continue
            raws.append(pathlib.Path(v["root"]) / v["level"])
    for raw in raws:
        if "_ded_" in raw.name:
            continue
        used += 1
        try:
            lvl = extracted(raw, dest)
            rows += rotations(lvl, raw, refs)
        except Exception as e:  # noqa: BLE001 (one broken level must not stop the census)
            print(f"skip {raw}: {e}", file=sys.stderr)
    if not rows:
        print("no rotations")
        return
    with open(dest / "rotacoes.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    groups = {}
    for r in rows:
        groups.setdefault((r["modo"], r["pesos_gb"]), []).append(r)
    md = ["# F5.0a — custo real da rotação (decisão → modelo que entra pronto)", "",
          "Gerado por `polyaxon/swap_cost.py`. Tempos em s, p50 / p90. `saída` = decisão → última vítima fora; "
          "`ciclo` = vítima fora → controlador decide ativar; `fila` = decisão de ativar → pedido no GPU scheduler; "
          "`carga` = pedido → pronto; `C_rot` = decisão → pronto (só rotações `ok`). `lapsed`: a ativação não veio em "
          f"{LAPSE_S:.0f} s. Níveis VALIDA usados: {used}; inválidos descartados: {dropped}.", "",
          "| modo de saída | pesos (GB) | rotações | ok / lapsed / vítima presa | saída | ciclo | fila | carga | C_rot | "
          "Ĉ_at | C_rot / Ĉ_at (p50) |", "|" + " --- |" * 11]
    c_rot = {}
    for (mode, wgb), rs in sorted(groups.items(), key=lambda k: (k[0][0], k[0][1] or 0)):
        ok = [r for r in rs if r["resultado"] == "ok"]
        cnt = lambda o: sum(r["resultado"] == o for r in rs)
        ratio = [r["c_rot"] / r["c_at"] for r in ok if r["c_at"]]
        col = lambda k, src=ok: f"{f(pct([r[k] for r in src], 50))} / {f(pct([r[k] for r in src], 90))}"
        md.append(f"| {mode} | {f(wgb)} | {len(rs)} | {cnt('ok')} / {cnt('lapsed')} / {cnt('victim_stuck')} | "
                  f"{col('saida', rs)} | {col('ciclo')} | {col('fila')} | {col('carga')} | {col('c_rot')} | "
                  f"{col('c_at')} | {f(statistics.median(ratio)) if ratio else '–'} |")
        if ok:
            c_rot.setdefault(mode, {})[str(wgb)] = {"n": len(ok), "p50": round(pct([r["c_rot"] for r in ok], 50), 3),
                                                     "p90": round(pct([r["c_rot"] for r in ok], 90), 3)}
    # S6 base (F5.0b): the fastest rotation the system does today, by model size = the preempting exit plus the wait
    # for a controller cycle (medians over every preempting rotation; they do not depend on the model entering) plus
    # the load time of the size from F2's activation-cost model with nothing ahead (Ĉ_at = a + b·weights, F2.3). The
    # measured loads of the preempting rotations agree with it for the 8B (1.4 s); loads measured in the other modes
    # overlap with victims still finishing and are not used. Measured C_rot with preemption is reported alongside.
    pre = [r for r in rows if r["modo"] == "preempt" and r["resultado"] == "ok"]
    overhead = (pct([r["saida"] for r in pre], 50) or 0.0) + max(0.0, pct([r["ciclo"] for r in pre], 50) or 0.0)
    sizes = sorted({r["pesos_gb"] for r in rows if r["pesos_gb"] is not None})
    s6 = {}
    for w in sizes:
        pw = [r for r in pre if r["pesos_gb"] == w]
        s6[str(w)] = {"c_at": round(c_at(w, 0), 3), "c_rot": round(overhead + c_at(w, 0), 3),
                      "medido_preempt_p50": round(pct([r["c_rot"] for r in pw], 50), 3) if pw else None,
                      "n_preempt": len(pw)}
    c_rot["s6"] = {"overhead_s": round(overhead, 3), "n_preempt": len(pre), "por_pesos_gb": s6}
    md += ["", f"**Base do S6** (`c_rot.json`, chave `s6`): Ĉ_rot(m) = saída com preempção + espera pelo ciclo "
               f"(medianas sobre {len(pre)} rotações com preempção: {f(overhead)} s) + Ĉ_at(m) sem ativações à frente "
               "(F2.3).", "",
           "| pesos (GB) | Ĉ_at (s) | Ĉ_rot (s) | C_rot medido com preempção, p50 (s) | n |",
           "| --- | --- | --- | --- | --- |"]
    for w, v in s6.items():
        md.append(f"| {f(float(w))} | {f(v['c_at'])} | {f(v['c_rot'])} | {f(v['medido_preempt_p50'])} | "
                  f"{v['n_preempt']} |")
    (dest / "resumo.md").write_text("\n".join(md) + "\n")
    (dest / "c_rot.json").write_text(json.dumps(c_rot, indent=2) + "\n")
    print(f"{dest}: {len(rows)} rotations, {sum(r['resultado'] == 'ok' for r in rows)} ok")


if __name__ == "__main__":
    sys.exit(main())
