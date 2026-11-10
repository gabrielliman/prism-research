"""SLO metrics with the SLO as a parameter (F2.11): three views, violation breakdown, avoidable/unavoidable split.

Usage:
  python3 polyaxon/slo_metrics.py level <level dir> [--slo SPEC ...]          one level, JSON
  python3 polyaxon/slo_metrics.py table <data dir> <dest.csv> [--slo SPEC ...] [--per-model <dest_models.csv>]
  python3 polyaxon/slo_metrics.py regress <data dir>                           S1 against <data dir>/metricas.csv
  python3 polyaxon/slo_metrics.py states <data dir> <dest.md>                  TTFT by model state at arrival (F2.6)

A level directory is what extract_ovl.py writes (summary.json, requests.csv, events.csv; config.json one level up);
a data directory is collect_reps.py's <scenario>/<config>/r<k>/<level>/. The SLO is never read from a constant: each
SPEC is a family and a level (PLANO_AGENTE.md section 5.4), default S1:ttft=1,tpot=0.1:
  S1:ttft=<s>,tpot=<s>    absolute, the same for every request
  S1D:ttft=<s>,kD=<k>     absolute TTFT, TPOT_r = kD · TPOT_base(m): the Prism paper's TPOT SLO (§7.1; its "TPOT SLO
                          scale" kD is 2.0-4.0 in §7.4 / Fig. 9b) next to the S1 TTFT; report standard (D56)
  S2:kT=<k>,kD=<k>        TTFT_r = kT · TTFT_base(m), TPOT_r = kD · TPOT_base(m)              (P95 base)
  S2M:kT=<k>,kD=<k>       the same with the P50 base (D21, the stable statistic)
  S3:kA=<k>,kD=<k>        TTFT_r = kA · Ĉ_at(m),      TPOT_r = kD · TPOT_base(m)
  S6:kR=<k>,kD=<k>        TTFT_r = kR · Ĉ_rot(m),     TPOT_r = kD · TPOT_base(m)   (D32, D39; Ĉ_rot from c_rot.json)
                          base WITHOUT preemption (D39 item 3, tested first): Ĉ_rot(m) = median measured rotation
                          whose victim finished its batch, by the entering model's weights (8B: 15.7 s)
  S6P:kR=<k>,kD=<k>       the same with the base WITH preemption: Ĉ_rot(m) = overhead_s (preempted exit + wait for
                          a controller cycle, 5.0 s) + Ĉ_at(m) (8B: 6.4 s)
  S2L:kT=<k>,kD=<k>       the first S2 (D18, superseded by D20): TTFT_r = kT · TTFT_iso(m, prompt_len_r),
                          TPOT_r = kD · TPOT_iso(m), from single-request probes (comparison only)
TTFT_base / TPOT_base (D20, the Prism paper's §7.1) are the P95 (S2, S3) or P50 (S2M) TTFT and TPOT of the requests
of the scenario's reference level served alone on a dedicated GPU, pooling the models of the scenario with the same
model_path (D21): reports/registro/latencia_ded.json ({scenario: {model: {pool_ttft_p95, pool_tpot_p95,
pool_ttft_p50, pool_tpot_p50, ...}}}, polyaxon/iso_dedicated.py; method in reports/registro/latencia_ref.md), looked up
by the level's scenario (the ovl_* part of its path; C9 ovl_classes takes the base of C1 or C6 under it, ded_key) and
model name. TTFT_iso / TPOT_iso come from
reports/registro/latencia_ref.json (D18: {model_path: {ttft_a, ttft_b, tpot_iso}}, TTFT_iso = ttft_a + ttft_b · L)
and Ĉ_at from reports/data/F02/cat/cat_model.json (F2.3, with no activation ahead). --ref / --ded / --cat override
the paths.

Definitions (PLANO_AGENTE.md section 7): a request meets a SLO when it was served and its TTFT ≤ SLO_TTFT (and/or
TPOT ≤ SLO_TPOT). Every fraction is over all sent requests; unserved and failed ones are misses in all three views.
In the TPOT view, served requests that generated fewer than 2 tokens have no TPOT and are left out of the numerator
and the denominator (their number is reported as tpot_excluidas). Breakdown (disjoint, sums to 1): ambos_ok,
viola_so_ttft, viola_so_tpot, viola_ambos (served), nao_atendidas (unserved + failed). A TTFT miss is unavoidable
when the request arrived while its model was inactive (deactivated, not activating) and SLO_TTFT_r < Ĉ_at(m);
unserved/failed requests are classified the same way. Model state at arrival comes from the GPU scheduler events
(act_req / act_ok / deact_ok) and the config's initial placement. This old split (viol_ttft_inevitavel / _evitavel,
F2.6, only Ĉ_at) is kept alongside the F5.0c one (PLANO_AGENTE.md section 7, D32), four disjoint groups of TTFT misses
over all sent requests, for a request that arrived while its model was inactive:
  viol_ttft_inev_ativacao   the controller's last free-memory reading at arrival (free_mem event) fits the model
                            (weights + 1 GB of activation KV, NEED_EXTRA_GB) and SLO_TTFT_r < Ĉ_at(m);
  viol_ttft_inev_rotacao    it did not fit, so someone had to leave, and SLO_TTFT_r < Ĉ_rot(m), the fastest rotation
                            today (with preemption, the S6P base: no policy rotates faster);
  viol_ttft_evit_residencia SLO_TTFT_r covers that cost (Ĉ_at or Ĉ_rot) but not that cost + one controller cycle
                            (median spacing of the free_mem readings, 5 s by default): only a decision taken before the
                            arrival (the model already resident or on its way) would have met it;
  viol_ttft_evit            every other TTFT miss, including all misses of requests whose model was active or
                            activating at arrival.
The need is a lower bound (A1.1 adds kvcached's floor and the KV of b requests), so "fits" is generous and Ĉ_at, the
smaller cost, is used more often: the unavoidable groups are, if anything, too small. TPOT cause (section 7.1):
viol_tpot_em_troca = TPOT misses (TPOT view) whose decode window [arrival + TTFT, arrival + latency] overlaps a model
transition (act_req → act_ok, controller evict → deact_ok), as a fraction of the TPOT view's requests.
"""
import csv
import json
import math
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REF = ROOT / "reports" / "registro" / "latencia_ref.json"
DED = ROOT / "reports" / "registro" / "latencia_ded.json"
CAT = ROOT / "reports" / "data" / "F02" / "cat" / "cat_model.json"
CROT = ROOT / "reports" / "registro" / "c_rot.json"  # F5.0a/b: S6 (sem_preempcao) and S6P (overhead_s + Ĉ_at) bases
MODEL_INFO = ROOT / "python" / "sglang" / "multi_model" / "utils" / "model_info.json"
PROFILED = {"meta-llama/Llama-3.1-8B-Instruct": 14.95755871385336,  # profiled at run time, not in model_info.json
            "Qwen/Qwen2.5-14B-Instruct": 27.511393651366234,  # C10 (run.log of f4-c10-1b, estimate_model_info)
            "Qwen/Qwen2.5-32B-Instruct": 61.027558386325836}
DEFAULT_SLO = "S1:ttft=1,tpot=0.1"
NEED_EXTRA_GB = 1.0  # activation KV on top of the weights (simple_global.py ACTIVATION_KV_GB, accounting on)
DEFAULT_CYCLE_S = 5.0  # PRISM_SCHEDULE_INTERVAL default (controller_global.py)


def parse_slo(spec):
    fam, _, rest = spec.partition(":")
    params = {k: float(v) for k, v in (kv.split("=") for kv in rest.split(",") if kv)}
    need = {"S1": {"ttft", "tpot"}, "S1D": {"ttft", "kD"}, "S2": {"kT", "kD"}, "S2M": {"kT", "kD"}, "S2L": {"kT", "kD"}, "S3": {"kA", "kD"}, "S6": {"kR", "kD"},
            "S6P": {"kR", "kD"}, "S4": {"kT", "kD", "bT"}}[fam]
    if set(params) != need:
        raise ValueError(f"{spec}: {fam} takes {sorted(need)}")
    return fam, params


class Refs:
    def __init__(self, ref=REF, cat=CAT, ded=DED):
        self.lat = json.load(open(ref)) if os.path.exists(ref) else None
        self.ded = json.load(open(ded)) if os.path.exists(ded) else None
        self.cat = json.load(open(cat)) if os.path.exists(cat) else None
        self.rot = json.load(open(CROT)) if os.path.exists(CROT) else None
        info = json.load(open(MODEL_INFO))
        self.weights = {k: v["model_size"] for k, v in info.items()} | PROFILED

    def c_at(self, path):
        if self.cat is None:
            raise FileNotFoundError(f"{CAT} (F2.3) is needed for S3 and the avoidable/unavoidable split")
        return self.cat["a"] + self.cat["b"] * self.weights[path]

    def c_rot(self, path, preempt=True):
        """Ĉ_rot(m), the real rotation time (D32, F5.0a/b). preempt=True (S6P): preempted victim's exit + wait for a
        controller cycle + Ĉ_at(m). preempt=False (S6, D39): median measured rotation whose victim finished its batch,
        looked up by the entering model's weights rounded to 0.1 GB as swap_cost.py keys them (nearest within 1 GB)."""
        if self.rot is None:
            raise FileNotFoundError(f"{CROT} (F5.0a, polyaxon/swap_cost.py) is needed for S6/S6P")
        if preempt:
            return self.rot["overhead_s"] + self.c_at(path)
        table = self.rot.get("sem_preempcao", {}).get("por_pesos_gb", {})
        w = self.weights[path]
        near = min(table, key=lambda k: abs(float(k) - w), default=None)
        if near is None or abs(float(near) - w) > 1.0:
            raise KeyError(f"no S6 base without preemption for {path} ({w:.1f} GB) in {CROT}: sizes {sorted(table)}")
        return table[near]["c_rot"]

    def iso(self, path):
        if self.lat is None or path not in self.lat:
            raise FileNotFoundError(f"TTFT_iso/TPOT_iso of {path} not in {REF} (F2.10)")
        return self.lat[path]

    def ded_entry(self, scenario, model, path=None):
        """latencia_ded.json entry of model in scenario; a model the dedicated runs did not have (the ρ_mem sweep's
        models 11-19, PRISM_OVL_N > 10) takes the entry of an identical model (same model_path) of the scenario, whose
        pool_* fields are the same for every identical model (D21, D44). None if neither exists."""
        sc = (self.ded or {}).get(scenario, {})
        if model in sc:
            return sc[model]
        same = [e for _, e in sorted(sc.items()) if path is not None and e.get("model_path") == path]
        return same[0] if same else None

    def base(self, scenario, model, q="p95", path=None):
        """(TTFT_base, TPOT_base) of model in scenario (D20), pooled over its identical models (D21), or None."""
        e = self.ded_entry(scenario, model, path)
        return (e[f"pool_ttft_{q}"], e[f"pool_tpot_{q}"]) if e and e.get(f"pool_ttft_{q}") is not None else None


def scenario_of(d):
    """The scenario of a level directory: the ovl_* part of its path (collect_reps.py and job layouts)."""
    return next((x for x in reversed(pathlib.Path(d).parts) if x.startswith("ovl_")), None)


def ded_key(scenario, pattern):
    """Key of latencia_ded.json for a scenario: C9 (ovl_classes) runs on C1 or C6 (PRISM_OVL_CLASS_BASE) and has no
    dedicated runs of its own; it uses the base of the load under it, told apart by the generator's pattern (C6 =
    zipf_drift, C1 = constant)."""
    if scenario == "ovl_classes":
        return "ovl_zipf" if pattern == "zipf_drift" else "ovl_mem"
    return scenario


def ded_scenario(d):
    """latencia_ded.json key of a level directory (scenario_of, with C9 resolved from summary.json args.pattern)."""
    sc = scenario_of(d)
    if sc == "ovl_classes":
        s = pathlib.Path(d) / "summary.json"
        return ded_key(sc, json.load(open(s))["args"].get("pattern") if s.exists() else None)
    return sc


def slo_of(req, path, fam, p, refs, base=None):
    """(SLO_TTFT, SLO_TPOT) of one request; base = (TTFT_base, TPOT_base) of its model (S2, S3)."""
    if fam == "S1":
        return p["ttft"], p["tpot"]
    if fam == "S2L":
        iso = refs.iso(path)
        return p["kT"] * (iso["ttft_a"] + iso["ttft_b"] * req["prompt_len"]), p["kD"] * iso["tpot_iso"]
    if base is None:
        raise FileNotFoundError(f"TTFT_base/TPOT_base of {req['model']} not in {DED} (D20, polyaxon/iso_dedicated.py)")
    if fam == "S1D":  # D56: the paper's TPOT SLO next to the absolute TTFT
        return p["ttft"], p["kD"] * base[1]
    if fam == "S4":  # F3.1, C9 classes (D19, provisional): interactive = S2 (kT, kD); batch = TTFT bT s, no TPOT limit
        if req.get("slo_class") == "batch":
            return p["bT"], math.inf
        return p["kT"] * base[0], p["kD"] * base[1]
    if fam in ("S2", "S2M"):
        return p["kT"] * base[0], p["kD"] * base[1]
    if fam in ("S6", "S6P"):
        return p["kR"] * refs.c_rot(path, preempt=fam == "S6P"), p["kD"] * base[1]
    return p["kA"] * refs.c_at(path), p["kD"] * base[1]


def bases_for(fam, scenario, models, refs):
    """model -> (TTFT_base, TPOT_base) or None: the P50 base for S2M, the P95 one otherwise (D20, D21). Used by the
    metrics and by overload_load.py --slo-spec (F6a.1), so the deadline sent and the one measured are the same."""
    q = "p50" if fam == "S2M" else "p95"
    return {m: refs.base(scenario, m, q, models[m] if isinstance(models, dict) else None) for m in models}


def load_level(d):
    d = pathlib.Path(d)
    reqs = []
    for r in csv.DictReader(open(d / "requests.csv")):
        num = lambda k: float(r[k]) if r.get(k) not in (None, "") else math.nan
        reqs.append({"id": r["id"], "model": r["model"], "arrival": float(r["arrival"]),
                     "prompt_len": int(r["prompt_len"]), "output_len": int(r["output_len"]), "status": r["status"],
                     "ttft": num("ttft"), "tpot": num("tpot"), "generated": num("generated"),
                     "latency": num("latency"),
                     "slo_class": r.get("slo_class") or "interactive"})
    ev = list(csv.DictReader(open(d / "events.csv"))) if (d / "events.csv").exists() else []
    cfg = json.load(open(d.parent / "config.json"))
    return reqs, ev, cfg


def state_at(ev, cfg):
    """model -> sorted [(t, state)] with state in {active, activating, inactive}."""
    ch = {m["model_name"]: [(-math.inf, "active" if m["init_placements"][0]["on"] else "inactive")] for m in cfg}
    for e in sorted(ev, key=lambda e: float(e["t"])):
        new = {"act_req": "activating", "act_ok": "active", "deact_ok": "inactive"}.get(e["kind"])
        if new and e["model"] in ch:
            ch[e["model"]].append((float(e["t"]), new))
    return ch


def lookup(changes, t):
    s = changes[0][1]
    for tc, st in changes:
        if tc > t:
            break
        s = st
    return s


def free_mem_series(ev):
    """Sorted [(t, free GB)] of the controller's free-memory readings, one per cycle."""
    return sorted((float(e["t"]), float(e["value"])) for e in ev if e["kind"] == "free_mem" and e["value"] != "")


def cycle_of(free):
    """Controller cycle length: median spacing of its free-memory readings (DEFAULT_CYCLE_S with < 3 readings)."""
    gaps = sorted(b[0] - a[0] for a, b in zip(free, free[1:]))
    return gaps[len(gaps) // 2] if len(gaps) >= 2 else DEFAULT_CYCLE_S


def free_at(free, t):
    """The last reading at or before t (the first one before any reading), or None without readings."""
    v = free[0][1] if free else None
    for tf, f in free:
        if tf > t:
            break
        v = f
    return v


def transitions(ev):
    """Sorted [(start, end)] of model transitions: act_req → act_ok and controller evict* → deact_ok (per model; an
    unmatched start runs to +inf)."""
    out, open_ = [], {}
    for e in sorted(ev, key=lambda e: float(e["t"])):
        t, k, m = float(e["t"]), e["kind"], e["model"]
        if (k == "act_req" or k.startswith("evict")) and m:
            open_.setdefault((m, "act" if k == "act_req" else "deact"), t)
        elif k in ("act_ok", "deact_ok", "stale_deact") and m:
            start = open_.pop((m, "act" if k == "act_ok" else "deact"), None)
            if start is not None:
                out.append((start, t))
    out += [(t, math.inf) for t in open_.values()]
    return sorted(out)


def overlaps(spans, a, b):
    return any(s < b and e > a for s, e in spans)


def classify_ttft_miss(inactive, slo_ttft, fits, c_at, c_rot, cycle):
    """F5.0c group of one TTFT miss (see the module docstring): inev_ativacao, inev_rotacao, evit_residencia, evit."""
    if not inactive:
        return "evit"
    cost, unav = (c_at, "inev_ativacao") if fits else (c_rot, "inev_rotacao")
    if slo_ttft < cost:
        return unav
    return "evit_residencia" if slo_ttft < cost + cycle else "evit"


def pct(xs, q):
    xs = sorted(x for x in xs if not math.isnan(x))
    if not xs:
        return math.nan
    k = (len(xs) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def evaluate(reqs, ev, cfg, spec, refs, per_model=False, scenario=None):
    fam, p = parse_slo(spec)
    path = {m["model_name"]: m["model_path"] for m in cfg}
    states = state_at(ev, cfg) if ev else None
    bases = bases_for(fam, scenario, path, refs)
    free = free_mem_series(ev)
    cycle = cycle_of(free)
    spans = transitions(ev)
    new_split = states is not None and refs.cat is not None and refs.rot is not None and bool(free)
    rows = []
    for r in reqs:
        base = bases[r["model"]]
        st, sp = slo_of(r, path[r["model"]], fam, p, refs, base)
        served = r["status"] == "ok"
        has_tpot = served and not (r["generated"] < 2)
        t_ok = served and r["ttft"] <= st
        d_ok = (has_tpot and r["tpot"] <= sp) or (served and not has_tpot)  # < 2 tokens: no TPOT to miss
        inactive = states is not None and lookup(states[r["model"]], r["arrival"]) == "inactive"
        unavoidable = None
        if refs.cat is not None and states is not None:
            unavoidable = inactive and st < refs.c_at(path[r["model"]])
        grupo = None
        if new_split and not t_ok:
            mp = path[r["model"]]
            fits = free_at(free, r["arrival"]) >= refs.weights[mp] + NEED_EXTRA_GB
            grupo = classify_ttft_miss(inactive, st, fits, refs.c_at(mp), refs.c_rot(mp, preempt=True), cycle)
        em_troca = None
        if has_tpot and not d_ok and ev:
            em_troca = overlaps(spans, r["arrival"] + r["ttft"], r["arrival"] + r["latency"])
        rows.append({"model": r["model"], "served": served, "has_tpot": has_tpot or not served, "t_ok": t_ok,
                     "d_ok": d_ok, "comb_ok": t_ok and d_ok, "inactive": inactive,
                     "unavoidable": unavoidable, "grupo": grupo, "em_troca": em_troca, "new_split": new_split,
                     "ttft": r["ttft"] if served else math.nan,
                     "tpot": r["tpot"] if has_tpot else math.nan,
                     "ttft_norm": r["ttft"] / base[0] if served and base else math.nan,
                     "tpot_norm": r["tpot"] / base[1] if has_tpot and base else math.nan})
    out = {"slo": spec, **summarize(rows)}
    if per_model:
        out["por_modelo"] = {m: summarize([x for x in rows if x["model"] == m]) for m in sorted({x["model"] for x in rows}, key=lambda s: int(s.split("_")[-1]))}
        out["pior_modelo_comb"] = min(v["comb"] for v in out["por_modelo"].values())
    return out


def summarize(rows):
    n = len(rows)
    srv = [x for x in rows if x["served"]]
    tp = [x for x in rows if x["has_tpot"]]  # TPOT view: served with >= 2 tokens, plus every unserved/failed
    viol_t = [x for x in rows if not x["t_ok"]]
    out = {
        "enviadas": n, "comb": sum(x["comb_ok"] for x in rows) / n, "so_ttft": sum(x["t_ok"] for x in rows) / n,
        "so_tpot": sum(x["d_ok"] for x in tp) / len(tp) if tp else math.nan, "tpot_excluidas": n - len(tp),
        "ambos_ok": sum(x["served"] and x["t_ok"] and x["d_ok"] for x in rows) / n,
        "viola_so_ttft": sum(x["served"] and not x["t_ok"] and x["d_ok"] for x in rows) / n,
        "viola_so_tpot": sum(x["served"] and x["t_ok"] and not x["d_ok"] for x in rows) / n,
        "viola_ambos": sum(x["served"] and not x["t_ok"] and not x["d_ok"] for x in rows) / n,
        "nao_atendidas": (n - len(srv)) / n,
        "chegou_inativo": sum(x["inactive"] for x in rows) / n,
    }
    if rows and rows[0]["unavoidable"] is not None:
        out["viol_ttft_inevitavel"] = sum(x["unavoidable"] for x in viol_t) / n
        out["viol_ttft_evitavel"] = (len(viol_t) - sum(x["unavoidable"] for x in viol_t)) / n
    if rows and rows[0]["new_split"]:
        for g in ("inev_ativacao", "inev_rotacao", "evit_residencia", "evit"):
            out[f"viol_ttft_{g}"] = sum(x["grupo"] == g for x in viol_t) / n
    if tp:
        out["viol_tpot_em_troca"] = sum(bool(x["em_troca"]) for x in tp) / len(tp)
    for k in ("ttft", "tpot", "ttft_norm", "tpot_norm"):
        for q in (50, 90, 99):
            out[f"{k}_p{q}"] = pct([x[k] for x in rows], q)
    return out


def level_metrics(d, specs, refs, per_model=False):
    reqs, ev, cfg = load_level(d)
    return [evaluate(reqs, ev, cfg, s, refs, per_model, ded_scenario(d)) for s in specs]


def levels(data):
    for s in sorted(pathlib.Path(data).rglob("summary.json")):
        d = s.parent
        parts = d.relative_to(data).parts
        if len(parts) == 4:
            yield d, parts


def table(data, dest, specs, refs, dest_models=None):
    rows, mrows = [], []
    for d, (scenario, config, rep, level) in levels(data):
        for m in level_metrics(d, specs, refs, per_model=True):
            key = {"cenário": scenario, "config": config, "nível": level, "rep": rep, "slo": m["slo"]}
            rows.append({**key, **{k: v for k, v in m.items() if k not in ("slo", "por_modelo")}})
            for model, v in m["por_modelo"].items():
                mrows.append({**key, "modelo": model, **v})
    write(dest, rows)
    if dest_models:
        write(dest_models, mrows)
    print(f"{dest}: {len(rows)} rows ({len(specs)} SLO definitions)")


def write(dest, rows):
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def regress(data, refs):
    """S1 at the October SLO must give the numbers of metricas.csv (overload_load.py's strict '<' vs '≤' here)."""
    old = {(r["cenário"], r["config"], r["nível"], r["rep"]): r for r in csv.DictReader(open(pathlib.Path(data) / "metricas.csv"))}
    worst, n = {}, 0
    for d, (scenario, config, rep, level) in levels(data):
        key = (scenario, config, level, rep)
        if key not in old:
            continue
        s = json.load(open(d / "summary.json"))["args"]
        spec = f"S1:ttft={s['slo_ttft']},tpot={s['slo_tpot']}"
        m = level_metrics(d, [spec], refs)[0]
        o = old[key]
        n += 1
        for new_k, old_k in (("comb", "SLO"), ("so_ttft", f"SLO TTFT < {s['slo_ttft']:g} s"),
                             ("so_tpot", f"SLO TPOT < {s['slo_tpot'] * 1000:.0f} ms"), ("ttft_p90", "TTFT p90 (s)")):
            if old_k in o and o[old_k] != "":
                diff = abs(m[new_k] - float(o[old_k]))
                if diff > worst.get(new_k, (0, None))[0]:
                    worst[new_k] = (diff, key)
                worst.setdefault(new_k, (0, None))
    print(f"{n} levels compared")
    for k, (diff, key) in worst.items():
        print(f"  {k}: max |new - old| = {diff:.3g}" + (f" at {'/'.join(key)}" if key else ""))
    return n > 0 and all(diff < 1e-9 for diff, _ in worst.values())


def states_table(data, dest):
    """F2.6 (observation 4.0): TTFT of the requests by their model's state at arrival, over every level of <data>."""
    agg = {}
    for d, (scenario, config, rep, level) in levels(data):
        reqs, ev, cfg = load_level(d)
        st = state_at(ev, cfg)
        for r in reqs:
            a = agg.setdefault((scenario, lookup(st[r["model"]], r["arrival"])), [0, 0, []])
            a[0] += 1
            if r["status"] == "ok":
                a[2].append(r["ttft"])
                a[1] += r["ttft"] <= 1.0
    name = {"active": "ativo", "activating": "ativando", "inactive": "inativo"}
    lines = [f"# TTFT pelo estado do modelo na chegada (gerado por `polyaxon/slo_metrics.py states {data}`)", "",
             "Todas as políticas e repetições do diretório. Frações sobre as enviadas; TTFT das atendidas.", "",
             "| Cenário | Estado na chegada | Requisições | TTFT ≤ 1 s | TTFT p10 (s) | p50 (s) | p90 (s) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for (sc, stt), (n, ok1, t) in sorted(agg.items()):
        lines.append(f"| {sc} | {name[stt]} | {n} | {ok1 / n:.1%} | {pct(t, 10):.2f} | {pct(t, 50):.2f} | {pct(t, 90):.2f} |")
    open(dest, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    args = sys.argv[1:]
    specs, ref, cat, ded, dm = [], REF, CAT, DED, None
    for flag in ("--slo", "--ref", "--cat", "--ded", "--per-model"):
        while flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            if flag == "--slo":
                specs.append(v)
            elif flag == "--ref":
                ref = v
            elif flag == "--cat":
                cat = v
            elif flag == "--ded":
                ded = v
            else:
                dm = v
    specs = specs or [DEFAULT_SLO]
    refs = Refs(ref, cat, ded)
    cmd = args[0]
    if cmd == "level":
        print(json.dumps(level_metrics(args[1], specs, refs, per_model=True), indent=1))
    elif cmd == "table":
        table(args[1], args[2], specs, refs, dm)
    elif cmd == "states":
        states_table(args[1], args[2])
    elif cmd == "regress":
        sys.exit(0 if regress(args[1], refs) else 1)


if __name__ == "__main__":
    main()
