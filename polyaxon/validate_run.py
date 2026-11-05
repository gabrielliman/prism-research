"""Run validator (F2.2): checks V1–V15 of PLANO_AGENTE.md section 3.1 on one level, and its classification.

Usage:
  python3 polyaxon/validate_run.py <level dir> [...]                       JSON per level
  python3 polyaxon/validate_run.py --csv <dest.csv> <downloads dir> [...]   every level under <dl>/<job>/outputs/

A level dir is the raw output of one load level (<job>/outputs/<config>/<step>/<level>/: requests.json, summary.json,
gpu.csv, health.log, server.log, server_file.log*). Each check gives OK, FALHA or N/A with the measured value:
  V1  server alive: no request failed by a connection error, and the controller still logging at the load end
  V2  zero worker deaths, aborts, kvcached driver failures (K1), torch OOM, pretty_print, worker exits, model service
      deaths and tracebacks inside the load window (shutdown tracebacks and "Error during cleanup" excluded)
  V3  no activation/deactivation longer than STUCK_FACTOR × the longest activation measured in F2.3, finished or not
  V4  no worker assigned to two models at once (the GPU scheduler's model_to_worker map)
  V5  sent = served + refused + expired: every request ends ok, refused (overload_load.py REFUSED_MARK, F3.1) or
      unserved (expired at the deadline); none failed
  V6  N/A until F7 (refusals with a reason)
  V7  retracted requests reappear and finish: OK when nothing was retracted or nothing went unserved; with
      PRISM_TRACE_RIDS logs, every unserved retracted request must sit in a queue (explained); otherwise N/A
  V8  served requests: 0 ≤ TTFT ≤ latency, TPOT ≥ 0, generated tokens = requested output length
  V9  TTFT not overwritten (S4): the server's TTFT ≤ the client's first streamed token + TTFT_TOL_S (client_ttft,
      overload_load.py from F2.1; N/A before)
  V10 generator and server share the container clock: with the wall-clock load start (F2.1), the p99 delay from
      send to server arrival within CLOCK_TOL_S (the log-based alignment is reported, not checked); before F2.1, the
      load start must be found by aligning arrivals with the GPU scheduler admissions
  V11 with the send times of F2.1 (requests.json "sent"): p99 send lag ≤ 1 s and total rate within ±5% of the
      target; N/A for older runs (decision pending, reports/registro/decisoes.md D10)
  V12 memory scenarios (ovl_mem, ovl_phases, ovl_mix, ovl_trace, ovl_trace_big and the F3 ones, MEMORY_STEPS) with models that start off the GPU
      (configs/<step>.json): overload evidence, at least one "No suitable GPU found" or GPU ≥ 95% used for
      ≥ OVERLOAD_FRAC of the window; N/A when every model starts resident (control levels such as n06, and the
      dedicated levels <level>_ded_<model> of D20, one model alone, configs/<step>_ded.json)
  V13 GPU used never above total; median |controller free memory − nvidia-smi free| ≤ FREE_TOL_GB
  V14 node health check passed before the level (health.log) and the level does not overlap a degraded-node window
      of reports/registro/janelas_degradadas.csv (UTC; the logs' local clock is converted with utc_offset_h; N/A
      when the job left no UTC start time); and the check right after the level passed (health_after.log, F2.2)
  V15 the load generator finished (summary.json): the job was not preempted
Classification: INVALIDA_INFRA when V14 or V15 fails (external evidence: degraded-node window, failed health check,
unfinished load); INVALIDA_SISTEMA when any other check fails; VALIDA otherwise. K1 and model service deaths are
flagged as infrastructure signals (sinal_infra, decisions D5/D6) but stay INVALIDA_SISTEMA outside a known window:
before R2.1 the controller itself caused K1 (P1), so K1 alone is not evidence of a degraded node. Informative: T1
(longest stretch with > 100 GB used, 0% utilization and an unserved request waiting), from classify_errors.frozen_s.
"""
import csv
import datetime
import glob
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify_errors as ce  # noqa: E402
import collect_reps  # noqa: E402
import extract_ovl as ex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.path.join(ROOT, "reports", "registro", "janelas_degradadas.csv")
CAT = os.path.join(ROOT, "reports", "data", "F02", "cat", "cat_model.json")
MEMORY_STEPS = {"ovl_mem", "ovl_phases", "ovl_mix", "ovl_trace", "ovl_trace_big",
                # F3 (C6-C10, T2-T5): memory overload by construction (more weights than the GPU holds)
                "ovl_zipf", "ovl_bursty", "ovl_diurnal", "ovl_classes", "ovl_sizes",
                "ovl_tr_lmsys", "ovl_tr_azfn", "ovl_tr_azllm", "ovl_tr_burst"}
STUCK_FACTOR = 3
OVERLOAD_FRAC = 0.10
FREE_TOL_GB = 2.0
END_SLACK_S = 30
TTFT_TOL_S = 0.05  # V9: server TTFT may exceed the client's first token only by the streaming delay
CLOCK_TOL_S = 1.0  # V10  # the controller logs every cycle (5 s); silent longer than this at the load end = not alive
INFRA_SIGNALS = {"k1", "model_service_died"}  # reported, but infrastructure only with external evidence (V14/V15)

ERR = {
    "k1": (("server.log", "server_file.log"), ce.K1),
    "torch_oom": (("server.log", "server_file.log"), re.compile(r"torch(\.cuda)?\.OutOfMemoryError")),
    "pretty_print": (("server.log", "server_file.log"), re.compile(r"^NotImplementedError\s*$")),
    "worker_died": (("server_file.log.gpu_scheduler.log",), re.compile(r" died \(serving|Worker \d+ on GPU \d+ died")),
    "worker_exit": (("server_file.log",), re.compile(r"Worker exits after an exception")),
    "abort": (("server.log",), re.compile(r"Aborted|core dumped|terminate called")),
    "model_service_died": (("server_file.log.gpu_scheduler.log",), re.compile(r"Model service \d+ died")),
    "traceback": (("server.log", "server_file.log", "server_file.log.gpu_scheduler.log",
                   "server_file.log.global_controller.log", "server_file.log.model_service.log"),
                  re.compile(r"Traceback \(most recent call last\)")),
}
ACT_REQ = re.compile(r"Received activate request for model (model_\d+)$")
ACT_OK = re.compile(r"Model (model_\d+) \(instance \d+\) activation succeeded")
DEACT_REQ = re.compile(r"Received deactivate request for (model_\d+),")
DEACT_OK = re.compile(r"Model (model_\d+) \(instance \d+\) deactivation succeeded")
ROLLBACK = re.compile(r"Model (model_\d+) lost on GPU|Ignoring the late deactivation of (model_\d+)")
M2W = re.compile(r"Current model_to_worker: (\{.*\})")


def chk(status, value=None, note=""):
    return {"status": status, "value": value, "note": note}


def windows():
    if not os.path.exists(WINDOWS):
        return []
    return [(ex.parse_ts(r["inicio_utc"]), ex.parse_ts(r["fim_utc"]), r["motivo"]) for r in csv.DictReader(open(WINDOWS))]


utc_offset_h = ex.utc_offset_h


def stuck_limit():
    if os.path.exists(CAT):
        m = json.load(open(CAT))
        return STUCK_FACTOR * max(v["max"] for v in m["per_weights_gb"].values())
    return STUCK_FACTOR * 60.0


def in_window(path, rx, t0, t1, exclude_after=None):
    n = 0
    for ts, line in ex.log_lines(path):
        if exclude_after is not None and ts >= exclude_after:
            break
        if t0 <= ts <= t1 and rx.search(line) and "Error during cleanup" not in line:
            n += 1
    return n


def cleanup_start(d):
    """Wall time the shutdown starts (the GPU scheduler's worker pool cleanup), after which tracebacks are expected."""
    for ts, line in ex.log_lines(os.path.join(d, "server_file.log.gpu_scheduler.log")):
        if "cleanup" in line.lower() and ("WorkerPool" in line or "Removed IPC file" in line):
            return ts
    return None


def spans(d):
    """Activation and deactivation spans (model, kind, start, end or None) from the GPU scheduler log."""
    out, open_ = [], {}
    for ts, line in ex.log_lines(os.path.join(d, "server_file.log.gpu_scheduler.log")):
        line = line.rstrip()
        for kind, rq, ok in (("activate", ACT_REQ, ACT_OK), ("deactivate", DEACT_REQ, DEACT_OK)):
            if m := rq.search(line):
                open_.setdefault((kind, m.group(1)), ts)
            elif m := ok.search(line):
                if (s := open_.pop((kind, m.group(1)), None)) is not None:
                    out.append((m.group(1), kind, s, ts))
        if m := ROLLBACK.search(line):  # failed activation / superseded deactivation: the span ends there
            model = m.group(1) or m.group(2)
            for kind in ("activate", "deactivate"):
                if (s := open_.pop((kind, model), None)) is not None:
                    out.append((model, kind, s, ts))
    out += [(m, k, s, None) for (k, m), s in open_.items()]
    return out


def double_assign(d):
    for ts, line in ex.log_lines(os.path.join(d, "server_file.log.gpu_scheduler.log")):
        if m := M2W.search(line):
            try:
                mw = eval(m.group(1), {"__builtins__": {}})  # a printed dict of str -> int
            except Exception:
                continue
            ws = list(mw.values())
            if len(ws) != len(set(ws)):
                return {"t": ts, "map": mw}
    return None


def trace_unexplained(d, unserved_ids):
    """Unserved requests whose last PRISM_TRACE_RIDS hop is not a queue (None when the level has no trace)."""
    hops = {}
    seen = False
    for name in ("server_file.log", "server_file.log.gpu_scheduler.log"):
        for ts, line in ex.log_lines(os.path.join(d, name)):
            if " RID " not in line:
                continue
            seen = True
            m = re.search(r"\] RID (\S+) (\S+) (.+)$", line.rstrip())
            if not m:
                continue
            rids = re.findall(r"[0-9a-f]{8,}|\b\d+\b", m.group(3))
            for rid in rids:
                hops.setdefault(rid, []).append((ts, m.group(1)))
    if not seen:
        return None
    queued = {"handler_to_frontend", "worker_to_frontend", "gpu_queue_to_frontend", "backend_to_frontend",
              "frontend_to_gpu_queue", "gpu_queue_to_backend"}
    bad = []
    for rid in unserved_ids:
        h = sorted(hops.get(rid, []))
        if h and h[-1][1] not in queued and h[-1][1] != "backend_to_worker":
            bad.append(rid)
    return bad


def validate(d):
    d = os.path.normpath(d)
    step = os.path.basename(os.path.dirname(d))
    res = {"level": d, "step": step}
    c = {}
    summ_p = os.path.join(d, "summary.json")
    if not os.path.exists(summ_p):
        c["V15"] = chk("FALHA", None, "no summary.json: the load did not finish")
        res.update(checks=c, status="INVALIDA_INFRA", failed=["V15"])
        return res
    s = json.load(open(summ_p))
    reqs = json.load(open(os.path.join(d, "requests.json")))
    dur = s["args"]["duration"]
    t0 = ex.load_start(d, reqs)
    t1 = (t0 or 0) + s["elapsed_s"]
    off = utc_offset_h(d)
    res["utc_offset_h"] = off
    s = {**s, "load_start_wall": s.get("load_start_wall")}
    # t0/t1 stay on the logs' clock (all log comparisons); u0/u1 are UTC, for the degraded-node windows
    u0, u1 = ((t0 + 3600 * off, t1 + 3600 * off) if t0 and off is not None else (None, None))
    res["t0_utc"] = datetime.datetime.fromtimestamp(u0).strftime("%Y-%m-%d %H:%M:%S") if u0 else None

    # V1
    conn = sum(r["status"] == "failed" and bool(ce.CONN.search(r.get("error") or "")) for r in reqs)
    last_ctrl = max((ts for ts, _ in ex.log_lines(os.path.join(d, "server_file.log.global_controller.log"))), default=None)
    alive = last_ctrl is not None and t0 is not None and last_ctrl >= t1 - END_SLACK_S
    c["V1"] = chk("OK" if conn == 0 and alive else "FALHA",
                  {"failed_conn": conn, "controller_silent_at_end_s": round(t1 - last_ctrl, 1) if last_ctrl and t0 else None})
    # V2
    cut = cleanup_start(d)
    counts = {}
    for k, (files, rx) in ERR.items():
        counts[k] = sum(in_window(os.path.join(d, f), rx, t0 or 0, t1, exclude_after=cut) for f in files)
    bad = {k: v for k, v in counts.items() if v}
    c["V2"] = chk("OK" if not bad else "FALHA", bad or 0)
    # V3
    lim = stuck_limit()
    long_ = [(m, k, round((e if e is not None else t1) - st, 1)) for m, k, st, e in spans(d)
             if st <= t1 and ((e if e is not None else t1) - st) > lim]
    c["V3"] = chk("OK" if not long_ else "FALHA", long_ or 0, f"limit {lim:.0f} s")
    # V4
    da = double_assign(d)
    c["V4"] = chk("OK" if da is None else "FALHA", da)
    # V5
    st = {}
    for r in reqs:
        st[r["status"]] = st.get(r["status"], 0) + 1
    v5ok = len(reqs) == s["sent"] and set(st) <= {"ok", "unserved", "refused"}
    c["V5"] = chk("OK" if v5ok else "FALHA", st)
    c["V6"] = chk("N/A", None, "refusals start in F7")
    # V7
    ev = ex.events(d, t0) if t0 else []
    retracted = sum(int(e[4] or 0) for e in ev if e[2] in ("preempt", "retract"))
    unserved = [r["id"] for r in reqs if r["status"] == "unserved"]
    if retracted == 0 or not unserved:
        c["V7"] = chk("OK", {"retracted": retracted, "unserved": len(unserved)})
    else:
        bad7 = trace_unexplained(d, unserved)
        if bad7 is None:
            c["V7"] = chk("N/A", {"retracted": retracted, "unserved": len(unserved)}, "no PRISM_TRACE_RIDS log")
        else:
            c["V7"] = chk("OK" if not bad7 else "FALHA", {"retracted": retracted, "unserved": len(unserved),
                                                         "unexplained": bad7[:20]})
    # V8
    inco = [r["id"] for r in reqs if r["status"] == "ok" and not (
        0 <= r["ttft"] <= r["latency"] + 1e-6 and r["tpot"] >= 0 and r["generated"] == r["output_len"])]
    c["V8"] = chk("OK" if not inco else "FALHA", {"incoherent": len(inco), "ids": inco[:10]})
    # V9: the server's TTFT (prefill finish − arrival) cannot exceed the first token the client saw; a later one is a
    # TTFT overwritten by a second prefill (S4). Needs client_ttft (overload_load.py from F2.1).
    both = [r for r in reqs if r["status"] == "ok" and r.get("client_ttft")]
    if both:
        over = [r["id"] for r in both if r["ttft"] > r["client_ttft"] + TTFT_TOL_S]
        c["V9"] = chk("OK" if not over else "FALHA", {"server_after_client": len(over), "ids": over[:10]})
    else:
        c["V9"] = chk("N/A", None, "no client-side TTFT (overload_load.py before F2.1)")
    # V10: generator and server share the container clock. With the load start's wall clock (F2.1) the log-based
    # alignment must agree with it, and the server must see each request shortly after it was sent.
    off = utc_offset_h(d)
    lsw = s.get("load_start_wall")
    if t0 is None:
        c["V10"] = chk("FALHA", None, "load start not found in the GPU scheduler log")
    elif lsw is not None and off is not None:
        lsw_log = lsw - 3600 * off  # the logs' clock is local time
        delays = sorted(r["server_arrival"] - (lsw + r["sent"]) for r in reqs if r.get("server_arrival") and r.get("sent") is not None)
        d99 = delays[min(len(delays) - 1, int(0.99 * len(delays)))] if delays else None
        # t0 is the wall-clock start itself here (extract_ovl.load_start); the log-based heuristic is informative
        # only: under compute overload admission lags the arrivals and it is seconds late (F2.8 runs)
        heur = ex.load_start_heuristic(d, reqs)
        ok10 = d99 is None or -CLOCK_TOL_S <= d99 <= CLOCK_TOL_S
        c["V10"] = chk("OK" if ok10 else "FALHA", {"send_to_server_p99_s": round(d99, 3) if d99 is not None else None,
                                                   "heuristic_vs_wall_s": round(heur - lsw_log, 3) if heur else None})
    else:
        c["V10"] = chk("OK", 0, "same container clock (no wall-clock load start before F2.1)")
    # V11
    if reqs and "sent" in reqs[0]:
        lag = sorted(r["sent"] - r["arrival"] for r in reqs)
        p99 = lag[min(len(lag) - 1, int(0.99 * len(lag)))]
        last = max(r["sent"] for r in reqs)
        rate_ok = abs(len(reqs) / max(last, 1e-9) - len(reqs) / dur) <= 0.05 * len(reqs) / dur if last >= 0.9 * dur else True
        c["V11"] = chk("OK" if p99 <= 1.0 and rate_ok else "FALHA", {"send_lag_p99_s": round(p99, 3)})
    else:
        c["V11"] = chk("N/A", None, "no send times (overload_load.py before F2.1)")
    # V12, V13
    gpu = ex.gpu_rows(os.path.join(d, "gpu.csv"), t0 or 0)
    win = [g for g in gpu if 0 <= g[0] <= dur]
    # dedicated levels (<level>_ded_<model>, run_examples.sh PRISM_OVL_DEDICATED, D20) ran one resident model
    ded = "_ded_" in os.path.basename(d)
    cfg = os.path.join(os.path.dirname(os.path.dirname(d)), "configs", f"{step}_ded.json" if ded else f"{step}.json")
    starts_off = None
    if os.path.exists(cfg):
        starts_off = sum(not m["init_placements"][0]["on"] for m in json.load(open(cfg)))
    if step in MEMORY_STEPS and starts_off != 0:
        no_fit = sum(e[2] == "no_fit" for e in ev if 0 <= e[0] <= dur)
        full = sum(g[1] >= 0.95 * g[2] for g in win) / len(win) if win else 0
        c["V12"] = chk("OK" if no_fit or full >= OVERLOAD_FRAC else "FALHA", {"no_fit": no_fit, "frac_gpu_95": round(full, 3)})
    else:
        c["V12"] = chk("N/A", None, f"{step} is not a memory overload scenario" if step not in MEMORY_STEPS
                       else "every model starts resident (control level, no memory overload by design)")
    over = sum(g[1] > g[2] for g in gpu)
    free = [(e[0], float(e[4])) for e in ev if e[2] == "free_mem"]
    diffs = []
    gi = 0
    for t, v in free:
        while gi + 1 < len(gpu) and abs(gpu[gi + 1][0] - t) <= abs(gpu[gi][0] - t):
            gi += 1
        if gpu and abs(gpu[gi][0] - t) <= 1.0:
            diffs.append(abs(v - (gpu[gi][2] - gpu[gi][1])))
    med = statistics.median(diffs) if diffs else None
    c["V13"] = chk("OK" if over == 0 and (med is None or med <= FREE_TOL_GB) else "FALHA",
                   {"samples_over_total": over, "median_abs_free_diff_gb": round(med, 2) if med is not None else None})
    # V14
    hl = open(os.path.join(d, "health.log"), errors="replace").read() if os.path.exists(os.path.join(d, "health.log")) else ""
    health_ok = bool(re.search(r"health: \d+/\d+ processes initialized", hl)) and "NODE UNHEALTHY" not in hl
    overl = [w[2] for w in windows() if u0 and w[0] <= u1 and w[1] >= u0]
    v14 = "OK" if (health_ok or not hl) and not overl else "FALHA"
    if u0 is None and v14 == "OK":
        v14 = "N/A"  # no UTC start (environment.txt or run.log): the window check cannot be made
    ha_p = os.path.join(d, "health_after.log")
    ha = open(ha_p, errors="replace").read() if os.path.exists(ha_p) else None
    after = "N/A" if ha is None else ("failed" if "unhealthy after" in ha else "ok")
    if after == "failed":
        v14 = "FALHA"
    c["V14"] = chk(v14, {"health_before": "ok" if health_ok else ("absent" if not hl else "failed"),
                         "degraded_windows": overl, "health_after": after, "utc_offset_h": off})
    # V15
    # summary.json exists, so the generator ran to its end (it can end a little before the window when every request
    # failed fast, which V1/V5 catch): the job was not preempted.
    c["V15"] = chk("OK", {"elapsed_s": round(s["elapsed_s"], 1), "duration": dur})

    res["t1_frozen_s"] = ce.frozen_s(d, reqs)
    failed = [k for k, v in c.items() if v["status"] == "FALHA"]
    infra = bool({"V14", "V15"} & set(failed))
    if set(bad) & INFRA_SIGNALS:
        res["sinal_infra"] = sorted(set(bad) & INFRA_SIGNALS)
    res.update(checks=c, failed=failed,
               status="VALIDA" if not failed else ("INVALIDA_INFRA" if infra else "INVALIDA_SISTEMA"),
               motivo="; ".join(f"{k}: {c[k]['value']}" for k in failed))
    return res


def batch(dest, roots):
    rows = []
    for root in roots:
        for s in sorted(glob.glob(os.path.join(root, "**", "ovl_*", "*", "requests.json"), recursive=True)):
            d = os.path.dirname(s)
            r = validate(d)
            job_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(d))))
            rows.append({"level": os.path.relpath(d, root), "root": root, "uuid": collect_reps.job_uuid(job_dir),
                         "source": os.path.relpath(d, os.path.dirname(job_dir)), "status": r["status"],
                         "failed": " ".join(r["failed"]), "motivo": r.get("motivo", ""), "t0_utc": r.get("t0_utc"),
                         "sinal_infra": " ".join(r.get("sinal_infra", [])),
                         "t1_frozen_s": r.get("t1_frozen_s"),
                         **{k: v["status"] for k, v in r["checks"].items()}})
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{dest}: {len(rows)} levels; " + ", ".join(f"{k} {sum(r['status'] == k for r in rows)}"
                                                       for k in ("VALIDA", "INVALIDA_INFRA", "INVALIDA_SISTEMA")))


def main():
    args = sys.argv[1:]
    if args[0] == "--csv":
        batch(args[1], args[2:])
    else:
        print(json.dumps([validate(d) for d in args], indent=1, default=str))


if __name__ == "__main__":
    main()
