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
  S2:kT=<k>,kD=<k>        TTFT_r = kT · TTFT_base(m), TPOT_r = kD · TPOT_base(m)              (P95 base)
  S2M:kT=<k>,kD=<k>       the same with the P50 base (D21, the stable statistic)
  S3:kA=<k>,kD=<k>        TTFT_r = kA · Ĉ_at(m),      TPOT_r = kD · TPOT_base(m)
  S2L:kT=<k>,kD=<k>       the first S2 (D18, superseded by D20): TTFT_r = kT · TTFT_iso(m, prompt_len_r),
                          TPOT_r = kD · TPOT_iso(m), from single-request probes (comparison only)
TTFT_base / TPOT_base (D20, the Prism paper's §7.1) are the P95 (S2, S3) or P50 (S2M) TTFT and TPOT of the requests
of the scenario's reference level served alone on a dedicated GPU, pooling the models of the scenario with the same
model_path (D21): reports/registro/latencia_ded.json ({scenario: {model: {pool_ttft_p95, pool_tpot_p95,
pool_ttft_p50, pool_tpot_p50, ...}}}, polyaxon/iso_dedicated.py; method in reports/registro/latencia_ref.md), looked up
by the level's scenario (the ovl_* part of its path) and model name. TTFT_iso / TPOT_iso come from
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
(act_req / act_ok / deact_ok) and the config's initial placement.
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
MODEL_INFO = ROOT / "python" / "sglang" / "multi_model" / "utils" / "model_info.json"
PROFILED = {"meta-llama/Llama-3.1-8B-Instruct": 14.95755871385336}  # profiled at run time, not in model_info.json
DEFAULT_SLO = "S1:ttft=1,tpot=0.1"


def parse_slo(spec):
    fam, _, rest = spec.partition(":")
    params = {k: float(v) for k, v in (kv.split("=") for kv in rest.split(",") if kv)}
    need = {"S1": {"ttft", "tpot"}, "S2": {"kT", "kD"}, "S2M": {"kT", "kD"}, "S2L": {"kT", "kD"}, "S3": {"kA", "kD"}}[fam]
    if set(params) != need:
        raise ValueError(f"{spec}: {fam} takes {sorted(need)}")
    return fam, params


class Refs:
    def __init__(self, ref=REF, cat=CAT, ded=DED):
        self.lat = json.load(open(ref)) if os.path.exists(ref) else None
        self.ded = json.load(open(ded)) if os.path.exists(ded) else None
        self.cat = json.load(open(cat)) if os.path.exists(cat) else None
        info = json.load(open(MODEL_INFO))
        self.weights = {k: v["model_size"] for k, v in info.items()} | PROFILED

    def c_at(self, path):
        if self.cat is None:
            raise FileNotFoundError(f"{CAT} (F2.3) is needed for S3 and the avoidable/unavoidable split")
        return self.cat["a"] + self.cat["b"] * self.weights[path]

    def iso(self, path):
        if self.lat is None or path not in self.lat:
            raise FileNotFoundError(f"TTFT_iso/TPOT_iso of {path} not in {REF} (F2.10)")
        return self.lat[path]

    def base(self, scenario, model, q="p95"):
        """(TTFT_base, TPOT_base) of model in scenario (D20), pooled over its identical models (D21), or None."""
        e = (self.ded or {}).get(scenario, {}).get(model)
        return (e[f"pool_ttft_{q}"], e[f"pool_tpot_{q}"]) if e and e.get(f"pool_ttft_{q}") is not None else None


def scenario_of(d):
    """The scenario of a level directory: the ovl_* part of its path (collect_reps.py and job layouts)."""
    return next((x for x in reversed(pathlib.Path(d).parts) if x.startswith("ovl_")), None)


def slo_of(req, path, fam, p, refs, base=None):
    """(SLO_TTFT, SLO_TPOT) of one request; base = (TTFT_base, TPOT_base) of its model (S2, S3)."""
    if fam == "S1":
        return p["ttft"], p["tpot"]
    if fam == "S2L":
        iso = refs.iso(path)
        return p["kT"] * (iso["ttft_a"] + iso["ttft_b"] * req["prompt_len"]), p["kD"] * iso["tpot_iso"]
    if base is None:
        raise FileNotFoundError(f"TTFT_base/TPOT_base of {req['model']} not in {DED} (D20, polyaxon/iso_dedicated.py)")
    if fam in ("S2", "S2M"):
        return p["kT"] * base[0], p["kD"] * base[1]
    return p["kA"] * refs.c_at(path), p["kD"] * base[1]


def load_level(d):
    d = pathlib.Path(d)
    reqs = []
    for r in csv.DictReader(open(d / "requests.csv")):
        num = lambda k: float(r[k]) if r.get(k) not in (None, "") else math.nan
        reqs.append({"id": r["id"], "model": r["model"], "arrival": float(r["arrival"]),
                     "prompt_len": int(r["prompt_len"]), "output_len": int(r["output_len"]), "status": r["status"],
                     "ttft": num("ttft"), "tpot": num("tpot"), "generated": num("generated")})
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
    bases = {m: refs.base(scenario, m, "p50" if fam == "S2M" else "p95") for m in path}
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
        rows.append({"model": r["model"], "served": served, "has_tpot": has_tpot or not served, "t_ok": t_ok,
                     "d_ok": d_ok, "comb_ok": t_ok and d_ok, "inactive": inactive,
                     "unavoidable": unavoidable, "ttft": r["ttft"] if served else math.nan,
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
    for k in ("ttft", "tpot", "ttft_norm", "tpot_norm"):
        for q in (50, 90, 99):
            out[f"{k}_p{q}"] = pct([x[k] for x in rows], q)
    return out


def level_metrics(d, specs, refs, per_model=False):
    reqs, ev, cfg = load_level(d)
    return [evaluate(reqs, ev, cfg, s, refs, per_model, scenario_of(d)) for s in specs]


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
