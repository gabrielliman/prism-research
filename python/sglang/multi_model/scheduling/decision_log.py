"""Structured log of the global controller's decisions (F2.1, PLANO_AGENTE.md section 0.5 / 3).

With PRISM_DECISION_LOG=<path> the policy appends one JSON line per scheduling cycle to <path>:
  {"t": wall clock, "cycle": n,
   "gpus": {gpu: {"free_gb": seen by get_available_gpu_memory, "pending_gb": promised to pending activations (R2.1),
                  "available_gb": free − pending, "pending": [models being activated]}},
   "models": {model: {"state": ACTIVE|INACTIVE as the policy sees it (first instance; ACTIVATING counts as ACTIVE,
                      DEACTIVATING as INACTIVE), "lifecycle": ACTIVE|INACTIVE|ACTIVATING|DEACTIVATING (D45), "gpu": [...],
                      "weights_gb", "waiting", "running", "oldest_wait_s", "min_deadline_in_s" (earliest
                      arrival + SLO of the waiting requests, minus t), "since_last_arrival_s",
                      "since_last_finish_s", "active_for_s", "running_rids" (only when the lifecycle is not
                      ACTIVE and the controller still counts running requests: P16 diagnosis)}},
   "actions": [{"kind": activate|deactivate|migrate, "model", "gpu", "reason", ...}],
   "notes": [{"kind": "no_fit", "model", "need_gb"}, {"kind": "reservation_lapsed" | "reservation_dropped", ...},
             ...],
   "policy": {"name": edf|lvf, "scores": {model: {"u", "viable", "lost", "active"} (edf) | {"vlt", "active"} (lvf)},
              "in_flight", "rotated_for"}}   (only with PRISM_EVICTION=edf|lvf, F6a.4)
Unset (the default), nothing is written and the policy behaves exactly as before: the log only reads the state the
policy already computed. validate_run.py and the analysis read it; the text log is unchanged.
"""
import json
import math
import os
import threading


def _view(state_name):
    """ACTIVATING counts as ACTIVE and DEACTIVATING as INACTIVE, as the policies see them (state.py ModelState)."""
    return {"ACTIVATING": "ACTIVE", "DEACTIVATING": "INACTIVE"}.get(state_name, state_name)


def _num(x):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(x, 3) if isinstance(x, float) else x


class DecisionLog:
    def __init__(self, path=None):
        path = path if path is not None else os.environ.get("PRISM_DECISION_LOG")
        self._f = open(path, "a", buffering=1) if path else None
        self._lock = threading.Lock()
        self._cycle = 0
        self._cur = None

    @property
    def enabled(self):
        return self._f is not None

    def begin(self, now):
        if not self.enabled:
            return
        self._cycle += 1
        self._cur = {"t": round(now, 3), "cycle": self._cycle, "gpus": {}, "models": {}, "actions": [], "notes": []}

    def gpu(self, gpu_id, free_gb, pending_gb, available_gb, pending):
        if self._cur is not None:
            self._cur["gpus"][str(gpu_id)] = {"free_gb": _num(free_gb), "pending_gb": _num(pending_gb),
                                              "available_gb": _num(available_gb), "pending": pending}

    def models(self, now, model_queues, model_instance_state_dict, weights, active_since):
        if self._cur is None:
            return
        for name, insts in model_instance_state_dict.items():
            q = model_queues.get(name)
            waiting = list(q.waiting_reqs) if q else []
            deadlines = [r.arrival_time + r.slo for r in waiting if getattr(r, "slo", None) is not None
                         and getattr(r, "arrival_time", None) is not None]
            oldest = q.get_earliest_arrival_time() if q else math.inf
            self._cur["models"][name] = {
                # the policy's two-state view, as before D45; the exact lifecycle in "lifecycle"
                "state": _view(insts[0].state.name) if insts else None,
                "lifecycle": insts[0].state.name if insts else None,
                "gpu": [g for i in insts for g in i.gpu_ids if _view(i.state.name) == "ACTIVE"],
                "weights_gb": _num(weights.get(name, {}).get("model_size")),
                "waiting": len(waiting), "running": q.get_num_running_reqs() if q else 0,
                "oldest_wait_s": _num(now - oldest) if math.isfinite(oldest) else None,
                "min_deadline_in_s": _num(min(deadlines) - now) if deadlines else None,
                "since_last_arrival_s": _num(now - q.get_last_arrival_time()) if q else None,
                "since_last_finish_s": _num(now - q.get_last_finished_time()) if q else None,
                "active_for_s": _num(now - active_since[name]) if name in active_since else None,
            }
            lifecycle = insts[0].state.name if insts else None
            if q and lifecycle != "ACTIVE" and q.running_reqs:
                self._cur["models"][name]["running_rids"] = [r.rid for r in q.running_reqs]

    def action(self, kind, model, gpu, reason, **extra):
        if self._cur is not None:
            self._cur["actions"].append({"kind": kind, "model": model, "gpu": gpu, "reason": reason,
                                         **{k: _num(v) for k, v in extra.items()}})

    def note(self, kind, model=None, **extra):
        if self._cur is not None:
            self._cur["notes"].append({"kind": kind, "model": model, **{k: _num(v) for k, v in extra.items()}})

    def policy(self, name, scores, **extra):
        if self._cur is not None:
            self._cur["policy"] = {"name": name, "scores": scores, **extra}

    def end(self):
        if self._cur is None:
            return
        with self._lock:
            self._f.write(json.dumps(self._cur, separators=(",", ":")) + "\n")
        self._cur = None
