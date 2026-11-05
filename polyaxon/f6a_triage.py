"""F6a.6 triage analysis (PLANO_AGENTE.md section 6, F6a; decisions D24–D26): paired, same-job comparison of the
deadline policies (A2.1 edf*, A9.1 lvf*) against the best baseline of the same job, in the three views of section 7.1.

Usage:
  /mnt/scratch/scheduler/opt-env/bin/python polyaxon/f6a_triage.py <dest dir> <validator.csv> [...]

Only levels the validator classified VALIDA are used (section 0.2). Each validator row names the downloaded level
(root + level). Every level is extracted (extract_ovl.extract_level) to <dest>/levels/<job>/<config>/<step>/<level>/
and evaluated with slo_metrics.py at the policy's own SLO spec (from the config name: S2k10, S2k25, S3k5); the
baselines (A0.*, fair) do not use the SLO, so they are evaluated at every spec after the run (section 5.4).

For each policy level, the reference is the better of A0.1 and A0.2 in the SAME job (same node, same window: the node
drifts 10–30% between jobs), per view. EDF levels of the stage-1 jobs (tri-c1-*, tri-t1-1: EDF v1, before the
D26 fixes) are reported apart, as diagnostics.

Writes:
  <dest>/niveis.csv     one row per (job, config, level, spec): the slo_metrics.py columns + rotations per minute
  <dest>/pareado.csv    one row per (job, policy level, view): value, A0.1, A0.2, best baseline, difference (pp)
  <dest>/resumo.md      mean paired difference per scenario, policy and view (+ per job), and the baselines of the
                        stage-1 jobs at each spec (A0.3 and fair included)
"""
import csv
import json
import math
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_ovl  # noqa: E402
import slo_metrics as sm  # noqa: E402

SPECS = {"S2k10": "S2:kT=10,kD=5", "S2k25": "S2:kT=25,kD=5", "S3k5": "S3:kA=5,kD=5"}
VIEWS = [("comb", "combinado"), ("so_ttft", "só TTFT"), ("so_tpot", "só TPOT"), ("pior_modelo_comb", "pior modelo")]
V1_JOBS = ("c1-1", "c1-2", "t1-1")  # stage-1 jobs: their EDF levels are EDF v1


def job_of(root):
    return os.path.basename(os.path.normpath(root))


def policy_spec(cfg):
    for tag, spec in SPECS.items():
        if cfg.endswith("_" + tag):
            return spec
    return None


def rotations_per_min(lvl_dir, summary):
    ev = list(csv.DictReader(open(lvl_dir / "events.csv"))) if (lvl_dir / "events.csv").exists() else []
    n = sum(e["kind"] in ("evict_edf", "evict_lvf", "evict_fair", "evict_swap", "evict_pressure") for e in ev)
    act = sum(e["kind"] == "act_req" for e in ev)
    dur = summary.get("elapsed_s") or 1.0
    return 60 * n / dur, 60 * act / dur


def main():
    dest = pathlib.Path(sys.argv[1])
    refs = sm.Refs()
    rows = []
    for vcsv in sys.argv[2:]:
        for v in csv.DictReader(open(vcsv)):
            if v["status"] != "VALIDA":
                continue
            src = pathlib.Path(v["root"]) / v["level"]  # outputs/<config>/<step>/<level>
            cfg, step, lvl = src.parts[-3], src.parts[-2], src.parts[-1]
            job = job_of(v["root"])
            out = dest / "levels" / job / cfg / step / lvl
            if not (out / "requests.csv").exists():
                extract_ovl.extract_level(str(src), str(out))
            if not (out.parent / "config.json").exists():
                shutil.copy(src.parents[1] / "configs" / f"{step}.json", out.parent / "config.json")
            summary = json.load(open(out / "summary.json"))
            rot, act = rotations_per_min(out, summary)
            spec = policy_spec(cfg)
            specs = [spec] if spec else list(SPECS.values())
            for m in sm.level_metrics(out, specs, refs, per_model=True):
                m = {k: x for k, x in m.items() if k != "por_modelo"}
                rows.append({"job": job, "cenário": step, "config": cfg, "nível": lvl, "uuid": v["uuid"],
                             "rotacoes_min": round(rot, 3), "ativacoes_min": round(act, 3), **m})
    dest.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0])
    with open(dest / "niveis.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)

    # paired differences
    by = {}
    for r in rows:
        by.setdefault((r["job"], r["slo"]), {})[r["config"]] = r
    pares = []
    for (job, spec), cfgs in sorted(by.items()):
        base = {b: cfgs.get(b) for b in ("A0.1", "A0.2")}
        if not all(base.values()):
            continue
        for cfg, r in cfgs.items():
            if policy_spec(cfg) != spec:
                continue
            versao = "v1" if cfg.startswith("edf") and job in V1_JOBS else ("v2" if cfg.startswith("edf") else "-")
            ciclo = "1 s" if "1s_" in cfg else "5 s"
            for col, _ in VIEWS + [("rotacoes_min", "rotações/min")]:
                b1, b2 = float(base["A0.1"][col]), float(base["A0.2"][col])
                val = float(r[col])
                pares.append({"job": job, "cenário": r["cenário"], "config": cfg, "versao": versao, "ciclo": ciclo,
                              "slo": spec, "vista": col, "valor": val, "A0.1": b1, "A0.2": b2,
                              "melhor_base": max(b1, b2),
                              "dif_pp": (val - max(b1, b2)) * (100 if col != "rotacoes_min" else 1)})
    with open(dest / "pareado.csv", "w", newline="") as f:
        w = csv.DictWriter(f, list(pares[0]))
        w.writeheader()
        w.writerows(pares)

    # summary
    md = ["# F6a.6 — triagem: diferença pareada contra a melhor linha de base do mesmo job", "",
          "Gerado por `polyaxon/f6a_triage.py`. Só níveis VALIDA. `dif` = política − max(A0.1, A0.2) do mesmo job, "
          "em pontos percentuais (rotações: por minuto). Bases do S2/S3: `reports/registro/latencia_ref.md`.", ""]
    groups = {}
    for p in pares:
        groups.setdefault((p["cenário"], p["config"], p["versao"], p["ciclo"], p["slo"]), {}).setdefault(
            p["vista"], []).append(p)
    for sc in sorted({k[0] for k in groups}):
        md += [f"## {sc}", "",
               "| política | versão | ciclo | SLO | reps | " + " | ".join(f"dif {n}" for _, n in VIEWS)
               + " | valor combinado | melhor base combinado | rotações/min |",
               "|" + " --- |" * (8 + len(VIEWS))]
        for k in sorted(k for k in groups if k[0] == sc):
            g = groups[k]
            mean = lambda xs: sum(xs) / len(xs)
            difs = [g[c] for c, _ in VIEWS]
            cells = []
            for ps in difs:
                ds = [p["dif_pp"] for p in ps]
                cells.append(f"{mean(ds):+.1f} ({', '.join(f'{d:+.1f}' for d in ds)})")
            comb = g["comb"]
            md.append(f"| {k[1]} | {k[2]} | {k[3]} | {k[4]} | {len(comb)} | " + " | ".join(cells)
                      + f" | {100 * mean([p['valor'] for p in comb]):.1f} | "
                        f"{100 * mean([p['melhor_base'] for p in comb]):.1f} | "
                        f"{mean([p['valor'] for p in g['rotacoes_min']]):.2f} |")
        md.append("")
    # baselines of the stage-1 jobs at each spec
    md += ["## Linhas de base dos jobs da etapa 1 (todas as especificações; combinado, %)", "",
           "| cenário | config | " + " | ".join(SPECS) + " |", "|" + " --- |" * (2 + len(SPECS))]
    base_rows = {}
    for r in rows:
        if r["job"] in V1_JOBS and policy_spec(r["config"]) is None:
            base_rows.setdefault((r["cenário"], r["config"]), {}).setdefault(r["slo"], []).append(float(r["comb"]))
    for (sc, cfg), d in sorted(base_rows.items()):
        md.append(f"| {sc} | {cfg} | " + " | ".join(
            f"{100 * sum(d[s]) / len(d[s]):.1f}" if s in d else "—" for s in SPECS.values()) + " |")
    (dest / "resumo.md").write_text("\n".join(md) + "\n")
    print(f"{dest}: {len(rows)} level×spec rows, {len(pares)} paired rows")


if __name__ == "__main__":
    main()
