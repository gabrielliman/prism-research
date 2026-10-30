"""Path of each unserved request through Prism's queues, from a level run with PRISM_TRACE_RIDS=1 (F1.2).

Usage: python3 polyaxon/trace_rids.py <level dir> [rid ...]

Reads the "RID <hop> <model> <rid or [rids]>" lines that the request handler, the GPU scheduler and the workers
log (server_file.log*), and prints, for every request the load generator reports as not served (requests.json) or
for the rids given, its hops in time order. Hops:
  handler_to_frontend      request handler -> Redis frontend queue of the model
  frontend_to_gpu_queue    GPU scheduler pops it into its priority queue (model activating/activated)
  gpu_queue_to_backend     GPU scheduler admits it to the model's Redis backend queue
  backend_to_worker        a worker serving the model takes it
  worker_to_frontend       a worker being deactivated (preempt) sends its waiting requests back
  gpu_queue_to_frontend    GPU scheduler returns its queued requests on deactivation
  backend_to_frontend      GPU scheduler returns the backend queue on deactivation
  handler_finished         the response is complete
Then a count of unserved requests by last hop.
"""
import ast
import collections
import glob
import json
import os
import re
import sys

LINE = re.compile(r"^\[(\S+ \S+)[^\]]*\] RID (\S+) (\S+) (.+)$")


def main():
    level, wanted = sys.argv[1], set(sys.argv[2:])
    if not wanted:
        wanted = {r["id"] for r in json.load(open(os.path.join(level, "requests.json"))) if r["status"] != "ok"}
    hops = collections.defaultdict(list)
    for path in glob.glob(os.path.join(level, "server_file.log*")):
        for line in open(path, errors="replace"):
            m = LINE.match(line.strip())
            if not m:
                continue
            ts, hop, model, rids = m.groups()
            rids = ast.literal_eval(rids) if rids.startswith("[") else [rids]
            for rid in rids:
                if rid in wanted:
                    hops[rid].append((ts, hop, model))
    last = collections.Counter()
    for rid in sorted(wanted, key=lambda r: (len(r), r)):
        path = sorted(hops.get(rid, []))
        last[path[-1][1] if path else "(no hop logged)"] += 1
        print(f"\n{rid}:")
        for ts, hop, model in path:
            print(f"  {ts}  {hop:22s} {model}")
    print(f"\n{len(wanted)} requests; last hop: {dict(last)}")


if __name__ == "__main__":
    main()
