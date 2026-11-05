"""Append runs to reports/registro/execucoes.csv (F2.7, PLANO_AGENTE.md section 3.3) from validate_run.py --csv.

Usage: python3 polyaxon/register_runs.py <validator.csv> --fase F02 --commit <hash> --suite <suite.tsv>
       [--cenario-de <suite line>=<id> ...]
       [--repetida-de <level>=<run_id> ...]

One row per level of the validator CSV not yet in the registry (run_id = <job uuid[:8]>/<suite line>/<step>/<level>).
Fields: date (UTC load start), phase, commit (the code the job uploaded; write "<hash>+diff" when it ran uncommitted
changes, saved under reports/data/<phase>/codigo/), image (environment.txt), scenario and level (step and level dir),
carga_id (workload hash, workload_stats.py), policy and parameters (the PRISM_* of the suite line, from the job's
--suite file), politica_usa_slo (1 for the policies that decide with the SLO, PRISM_EVICTION in SLO_POLICIES, with the
family and level of the PRISM_OVL_SLO_SPEC the job sent, e.g. S2 / kT=10,kD=5; 0 with family/level empty for the others,
whose curves are computed afterwards, section 5.4: the curves
are computed afterwards), seed (summary.json), repetition (k-th level of the same suite line and step in the
registry), GPU and node (environment.txt), validator status, failed checks and reason, artifacts path.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workload_stats as ws  # noqa: E402

SLO_POLICIES = {"edf", "lvf"}  # F6a: A2.1, A9.1 (they read the per-request deadline)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "reports", "registro", "execucoes.csv")


def main():
    args = sys.argv[1:]
    opts, pairs = {}, {"--cenario-de": {}, "--repetida-de": {}}
    for flag in ("--fase", "--commit", "--suite"):
        if flag in args:
            i = args.index(flag)
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    for flag in pairs:
        while flag in args:
            i = args.index(flag)
            k, v = args[i + 1].split("=", 1)
            pairs[flag][k] = v
            del args[i:i + 2]
    vcsv = args[0]
    suite = {}
    if "--suite" in opts:
        for ln in open(opts["--suite"]):
            if ln.strip() and not ln.startswith("#"):
                name, _, vars_ = ln.rstrip("\n").partition("\t")
                suite[name] = dict(kv.split("=", 1) for kv in vars_.split() if "=" in kv)
    reg = list(csv.DictReader(open(REG)))
    cols = open(REG).readline().strip().split(",")
    have = {r["run_id"] for r in reg}
    new = []
    for v in csv.DictReader(open(vcsv)):
        d = os.path.join(v["root"], v["level"])
        parts = v["level"].split(os.sep)
        line, step, level = parts[-3], parts[-2], parts[-1]
        run_id = f"{v['uuid'][:8]}/{line}/{step}/{level}"
        if run_id in have:
            continue
        env = open(os.path.join(os.path.dirname(os.path.dirname(d)), "environment.txt"), errors="replace").read() \
            if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(d)), "environment.txt")) else ""
        s = json.load(open(os.path.join(d, "summary.json")))
        params = suite.get(line, {})
        pol = {k: v_ for k, v_ in params.items() if k.startswith("PRISM_") and k not in ("PRISM_STEPS", "PRISM_OVL_RATES")}
        rep = 1 + sum(r["politica"] == line and r["cenario"] == step and r["nivel"] == level for r in reg + new)
        img = re.search(r"image[: ]+(\S+)", env)
        gpu = re.search(r"(NVIDIA H\d+\S*)", env)
        usa_slo = params.get("PRISM_EVICTION") in SLO_POLICIES
        fam, _, lvl = params.get("PRISM_OVL_SLO_SPEC", "").partition(":") if usa_slo else ("", "", "")
        host = re.search(r"host: (\S+)", env)
        new.append({
            "run_id": run_id, "data": v.get("t0_utc") or "", "fase": opts.get("--fase", ""),
            "commit": opts.get("--commit", ""), "imagem": img.group(1) if img else "gabrielliman/prism:sglang0.3.4-cu121",
            "cenario": pairs["--cenario-de"].get(line, step), "carga_id": ws.stats(d)["sha256"][:16], "nivel": level,
            "politica": line, "parametros": json.dumps(pol, ensure_ascii=False), "politica_usa_slo": "1" if usa_slo else "0",
            "slo_familia": fam, "slo_nivel": lvl, "semente": s["args"].get("seed", ""), "repeticao": rep,
            "gpu": gpu.group(1).strip() if gpu else "H200", "no": host.group(1) if host else "",
            "status_validador": v["status"], "verificacoes_falhas": v["failed"], "motivo": v["motivo"],
            "repetida_de": pairs["--repetida-de"].get(run_id, ""),
            "caminho_artefatos": os.path.relpath(d, "/mnt/scratch/scheduler") if d.startswith("/mnt/scratch/scheduler") else d})
    with open(REG, "a", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writerows(new)
    print(f"{REG}: {len(new)} new rows")


if __name__ == "__main__":
    main()
