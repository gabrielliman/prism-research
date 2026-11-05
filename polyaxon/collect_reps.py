"""Merge the clean levels of several download rounds into one data directory, with a manifest.

Usage: python3 polyaxon/collect_reps.py <dest dir> <round>=<downloads dir>[:lossless] [...]

Each downloads dir holds <job>/outputs/<config>/<step>/<level>/ (one folder per job, as
`polyaxon ops artifacts ... --path <downloads dir>/<job>` leaves it); <job> is the suite name plus "-<rep>"
(mem-idle-1, tp-mix-2, ...), <config> the suite line name (a fill suite may append "_<level>").

A level is kept only when validate_run.py (F2.2, PLANO_AGENTE.md sections 0.2 and 3.1) classifies it VALIDA: invalid
levels never enter an aggregate. Dropped levels go to <dest>/descartados.csv (scenario, config, level, round, job,
uuid, source, status, failed checks, reason). PRISM_COLLECT_CRITERION=legacy restores the pre-F2 criterion, only to
reproduce the reports written before the validator (F0, F1, October 2026): a level was clean when its server never hit
a kvcached driver abort (cuMem* in server.log), a torch OOM, the SGLang pretty_print crash or a dead worker.
In a ":lossless" round (one that ran before the prefill and
deactivation-race fixes, whose losses may come from them) a level must also lose no request, except Prism's
original policy in ovl_mix, which freezes by itself. Rounds listed first are preferred. Each (scenario, config, level)
keeps up to PRISM_REPS (default 3) clean levels; Prism's original policy (idle50 of the threshold suites, base* of the others: the
same configuration) keeps every clean level it has.

Writes <dest>/<scenario>/<config>/r<k>/<level>/ (extract_ovl.extract_level), r<k>/config.json, and
<dest>/manifest.csv (scenario, config, level, rep, round, job, uuid, source, status).
"""
import csv
import glob
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_ovl  # noqa: E402

STRATEGY = {"pressure_phases": "pressure", "adaptive_trace12": "adaptive", "headroom_mem": "headroom", "headroom_mix": "headroom",
            "fair_mem": "fair"}
REPS = int(os.environ.get("PRISM_REPS", 3))  # clean levels kept per configuration (F1.3 keeps 5)
CRITERION = os.environ.get("PRISM_COLLECT_CRITERION", "validator")  # validator | legacy


def canonical(cfg):
    cfg = re.sub(r"_(rate|ts)[0-9.]+$", "", cfg)
    if cfg == "idle50" or cfg.startswith("base"):
        return "original"
    return STRATEGY.get(cfg, cfg)


def clean(level):
    def read(name):
        path = os.path.join(level, name)
        return open(path, errors="replace").read() if os.path.exists(path) else ""
    sf = read("server_file.log")
    return not ("cuMem" in read("server.log") or "torch.OutOfMemoryError" in sf
                or re.search(r"^NotImplementedError$", sf, re.M)
                or " died (serving" in read("server_file.log.gpu_scheduler.log"))


def classify(level):
    """(keep, status, failed checks, reason) of one level under CRITERION."""
    if CRITERION == "legacy":
        ok = clean(level)
        return ok, "LIMPO" if ok else "SUJO", "", "" if ok else "collect_reps.clean (legacy)"
    import validate_run  # lazy: validate_run imports this module
    r = validate_run.validate(level)
    return r["status"] == "VALIDA", r["status"], " ".join(r["failed"]), r.get("motivo", "")


def job_uuid(job_dir):
    for log in glob.glob(os.path.join(job_dir, "outputs", "*", "run.log")):
        if m := re.search(r"artifacts/([0-9a-f]{32})", open(log, errors="replace").read()):
            return m.group(1)
    return ""


def main():
    dest, rounds = sys.argv[1], [a.split("=", 1) for a in sys.argv[2:]]
    found = {}  # (scenario, config, level) -> [(round, job, uuid, level dir, config dir, status)]
    dropped = []
    for round_, root in rounds:
        root, lossless = (root[:-9], True) if root.endswith(":lossless") else (root, False)
        for job_dir in sorted(glob.glob(os.path.join(root, "*"))):
            uuid = job_uuid(job_dir)
            for level in sorted(glob.glob(os.path.join(job_dir, "outputs", "*", "ovl_*", "*", "summary.json"))):
                level = os.path.dirname(level)
                cfg_dir, step = os.path.dirname(os.path.dirname(level)), os.path.basename(os.path.dirname(level))
                key = (step, canonical(os.path.basename(cfg_dir)), os.path.basename(level))
                if lossless and key[:2] != ("ovl_mix", "original"):
                    summary = json.load(open(os.path.join(level, "summary.json")))
                    if summary["unserved"] + summary["failed"]:
                        continue
                keep, status, failed, reason = classify(level)
                if keep:
                    found.setdefault(key, []).append((round_, os.path.basename(job_dir), uuid, level, cfg_dir, status))
                else:
                    dropped.append([*key, round_, os.path.basename(job_dir), uuid,
                                    os.path.relpath(level, root), status, failed, reason])
    rows = []
    for (step, cfg, lvl), runs in sorted(found.items()):
        for k, (round_, job, uuid, level, cfg_dir, status) in enumerate(runs if cfg == "original" else runs[:REPS], 1):
            rep = os.path.join(dest, step, cfg, f"r{k}")
            os.makedirs(rep, exist_ok=True)
            shutil.copy(os.path.join(cfg_dir, "configs", f"{step}.json"), os.path.join(rep, "config.json"))
            extract_ovl.extract_level(level, os.path.join(rep, lvl))
            rows.append([step, cfg, lvl, k, round_, job, uuid,
                         os.path.relpath(level, os.path.dirname(os.path.dirname(os.path.dirname(cfg_dir)))), status])
    with open(os.path.join(dest, "manifest.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "config", "level", "rep", "round", "job", "uuid", "source", "status"])
        w.writerows(rows)
    with open(os.path.join(dest, "descartados.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "config", "level", "round", "job", "uuid", "source", "status", "failed", "reason"])
        w.writerows(dropped)
    print(f"{dest}: {len(rows)} levels kept, {len(dropped)} dropped (criterion {CRITERION})")


if __name__ == "__main__":
    main()
