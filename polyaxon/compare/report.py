"""Compares the outputs of the backend comparison runs and prints Markdown tables.

Usage: python3 polyaxon/compare/report.py <sglang outputs dir> <vllm outputs dir>
Each dir is a run's downloaded `outputs/` (several runs can be merged into one dir: steps are subdirs).
"""
import csv
import glob
import json
import os
import re
import statistics
import sys

SG, VL = sys.argv[1], sys.argv[2]
NAMES = {SG: "SGLang", VL: "vLLM"}


def load_json(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def key_metrics(step_dir):
    rows = []
    for f in sorted(glob.glob(os.path.join(step_dir, "**", "*key_metrics.tsv"), recursive=True)):
        with open(f) as fh:
            rows.extend(csv.DictReader(fh, delimiter="\t"))
    return rows


def fnum(x, scale=1.0, nd=1):
    try:
        return f"{float(x) * scale:.{nd}f}"
    except Exception:
        return "—"


def med(xs):
    return statistics.median(xs) if xs else float("nan")


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ---------------------------------------------------------------- parity
print("## Paridade de API e de saída (cmp_parity/parity.json)\n")
par = {d: load_json(os.path.join(d, "cmp_parity", "parity.json")) for d in (SG, VL)}
if all(par.values()):
    by = {d: {(r["model"], r["case"], r["prompt"]): r for r in par[d]} for d in (SG, VL)}
    cases = sorted({k[1] for k in by[SG]}, key=lambda c: [r["case"] for r in par[SG]].index(c))
    print("| caso | ok SGLang | ok vLLM | texto idêntico | prefixo comum médio | mesmo nº tokens | finish SGLang | finish vLLM | verificação |")
    print("|---|---|---|---|---|---|---|---|---|")
    for case in cases:
        keys = [k for k in by[SG] if k[1] == case]
        ok = {d: sum(1 for k in keys if by[d].get(k, {}).get("status") == 200) for d in (SG, VL)}
        same, pref, ntok, fin = 0, [], 0, {SG: {}, VL: {}}
        check_ok = {SG: 0, VL: 0}
        for k in keys:
            r = {d: by[d].get(k, {}).get("response", {}) for d in (SG, VL)}
            t = {d: r[d].get("text", "") if isinstance(r[d], dict) else "" for d in (SG, VL)}
            mi = {d: (r[d].get("meta_info") or {}) if isinstance(r[d], dict) else {} for d in (SG, VL)}
            same += t[SG] == t[VL]
            pref.append(common_prefix(t[SG], t[VL]) / max(len(t[SG]), len(t[VL]), 1))
            ntok += mi[SG].get("completion_tokens") == mi[VL].get("completion_tokens")
            for d in (SG, VL):
                fr = (mi[d].get("finish_reason") or {}).get("type", "none")
                fin[d][fr] = fin[d].get(fr, 0) + 1
                p = by[d].get(k, {}).get("params", {})
                c = mi[d].get("completion_tokens") or 0
                if case == "regex_digits":
                    check_ok[d] += bool(re.fullmatch(p["regex"], t[d]))
                elif case == "stop_str":
                    check_ok[d] += "." not in t[d]
                elif case == "stop_str_no_trim":
                    check_ok[d] += t[d].endswith(".") or c >= p["max_new_tokens"]
                elif case == "min_tokens":
                    check_ok[d] += c >= p["min_new_tokens"]
                elif case in ("one_token", "ignore_eos", "greedy_64"):
                    check_ok[d] += c == p["max_new_tokens"] or case == "greedy_64" and c <= 64
                else:
                    check_ok[d] += c <= p["max_new_tokens"]
        n = len(keys)
        fins = {d: ", ".join(f"{a}:{b}" for a, b in sorted(fin[d].items())) for d in (SG, VL)}
        print(f"| {case} | {ok[SG]}/{n} | {ok[VL]}/{n} | {same}/{n} | {100 * sum(pref) / n:.0f}% | {ntok}/{n} "
              f"| {fins[SG]} | {fins[VL]} | SGLang {check_ok[SG]}/{n}, vLLM {check_ok[VL]}/{n} |")
    meta = {d: sorted({k for r in par[d] if isinstance(r["response"], dict) for k in (r["response"].get("meta_info") or {})}) for d in (SG, VL)}
    print(f"\nChaves de meta_info só no SGLang: {sorted(set(meta[SG]) - set(meta[VL])) or 'nenhuma'}; "
          f"só no vLLM: {sorted(set(meta[VL]) - set(meta[SG])) or 'nenhuma'}.\n")
    errs = {d: [r for r in par[d] if r["status"] != 200][:3] for d in (SG, VL)}
    for d in (SG, VL):
        for r in errs[d]:
            print(f"- erro {NAMES[d]} {r['model']}/{r['case']}: `{str(r['response'])[:200]}`")
else:
    print("(sem dados)\n")

# ------------------------------------------------------------ activation
print("\n## Ativação/desativação (cmp_parity/activation.json, 10 ciclos ociosos)\n")
act = {d: load_json(os.path.join(d, "cmp_parity", "activation.json")) for d in (SG, VL)}
if all(act.values()):
    print("| modelo | backend | desativar (mediana) | ativar (mediana) | ativar (máx) | GB liberados (mediana) | saída igual após ativar |")
    print("|---|---|---|---|---|---|---|")
    for m, label in (("model_1", "Llama-3.1-8B"), ("model_2", "Llama-3.2-3B")):
        for d in (SG, VL):
            x = act[d]["models"][m]
            print(f"| {label} | {NAMES[d]} | {med(x['deactivate_s']):.3f}s | {med(x['activate_s']):.3f}s | "
                  f"{max(x['activate_s']):.3f}s | {med(x['freed_gb']):.2f} | {x['all_ok']} |")
    print("\n| backend | GPU com os 2 ativos | GPU com os 2 desativados | memória por engine desativado |")
    print("|---|---|---|---|")
    for d in (SG, VL):
        a = act[d]
        print(f"| {NAMES[d]} | {a['both_active_gb'] - a['baseline_gb']:.1f} GB | "
              f"{a['both_inactive_gb'] - a['baseline_gb']:.1f} GB | {a['idle_engine_gb']:.2f} GB |")
else:
    print("(sem dados)\n")

# ------------------------------------------------------------ load sweep
print("\n## Desempenho sob carga (2 modelos sempre ativos, trace sintético 60 s)\n")
print("| passo | taxa | backend | req/s | tok/s saída | TTFT médio (ms) | TTFT p99 (ms) | TPOT médio (ms) | TPOT p99 (ms) | E2E médio (s) |")
print("|---|---|---|---|---|---|---|---|---|---|")
for step in ("cmp_sweep", "cmp_graph"):
    for rate in (5, 10, 20):
        for d in (SG, VL):
            rows = key_metrics(os.path.join(d, step, f"rate{rate}"))
            r = next((x for x in rows if x.get("exp_name", "").endswith(f"rate{rate}")), rows[0] if rows else None)
            if not r:
                print(f"| {step} | {rate} | {NAMES[d]} | falhou | | | | | | |")
                continue
            print(f"| {step} | {rate} | {NAMES[d]} | {fnum(r['Request Tput (req/s)'], nd=2)} | {fnum(r['Output Token Tput (tok/s)'], nd=0)} "
                  f"| {fnum(r['Mean TTFT (s)'], 1000)} | {fnum(r['P99 TTFT (s)'], 1000)} | {fnum(r['Mean TPOT (ms)'])} "
                  f"| {fnum(r['P99 TPOT (ms)'])} | {fnum(r['Mean E2E Latency (s)'], nd=2)} |")

# ------------------------------------------------------- README examples
print("\n## Exemplos do README\n")
print("| passo | backend | req/s | tok/s saída | TTFT médio (ms) | TPOT médio (ms) | E2E médio (s) |")
print("|---|---|---|---|---|---|---|")
for step in ("static", "elastic", "prism1", "prism2"):
    for d in (SG, VL):
        rows = key_metrics(os.path.join(d, step))
        if not rows:
            log = os.path.join(d, step, "benchmark.log")
            done = re.findall(r"Completed requests: (\d+)", open(log).read()) if os.path.exists(log) else []
            print(f"| {step} | {NAMES[d]} | {'concluídas ' + done[-1] if done else 'sem métricas'} | | | | |")
            continue
        r = rows[-1]
        print(f"| {step} | {NAMES[d]} | {fnum(r['Request Tput (req/s)'], nd=2)} | {fnum(r['Output Token Tput (tok/s)'], nd=0)} "
              f"| {fnum(r['Mean TTFT (s)'], 1000)} | {fnum(r['Mean TPOT (ms)'])} | {fnum(r['Mean E2E Latency (s)'], nd=2)} |")

# ------------------------------------------------------------- switching
print("\n## Teste de troca de modelos (test_switching.py)\n")
for step in ("switch_static", "switch_elastic"):
    res = {}
    for d in (SG, VL):
        log = os.path.join(d, step, "test_switching.log")
        res[d] = {}
        if os.path.exists(log):
            for line in open(log):
                m = re.match(r"\[(PASS|FAIL|INFO)\] (.*?)(?: (\d.*|first.*|True.*|False.*))?$", line.strip())
                if m and m.group(1) != "INFO":
                    res[d][m.group(2).split(" {")[0].strip()] = m.group(1)
                elif m:
                    res[d]["(info) " + m.group(2)[:60]] = line.strip()[7:120]
    names = list(dict.fromkeys(list(res[SG]) + list(res[VL])))
    print(f"\n**{step}**\n\n| verificação | SGLang | vLLM |\n|---|---|---|")
    for n in names:
        print(f"| {n} | {res[SG].get(n, '—')} | {res[VL].get(n, '—')} |")
