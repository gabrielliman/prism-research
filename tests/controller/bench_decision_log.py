"""F2.8: cost of the controller decision log per scheduling cycle (DecisionLog), 12 models with 50 waiting requests
each, 4 actions and a note per cycle, 2000 cycles. Run: /mnt/scratch/scheduler/opt-env/bin/python tests/controller/bench_decision_log.py
"""
import sys, os, time, tempfile, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_decision_log as t  # loads the policy modules with stubs
from sglang.multi_model.scheduling.decision_log import DecisionLog
mqt, st = t.mqt, t.st
now = time.time()
mem = types.SimpleNamespace(model_weights_memory=15.0, memory_pool_memory=1.0)
insts, queues, w = {}, {}, {}
for i in range(1, 13):
    n = f"model_{i}"
    insts[n] = [st.ModelInstanceState(model_name=n, model_path="p", instance_idx=0, gpu_ids=[0],
                state=st.ModelState.ACTIVE if i <= 6 else st.ModelState.INACTIVE, memory_usage=mem, init_memory_pool_size=6.0)]
    q = mqt.ModelQueueTracker(n)
    for k in range(50):  # 50 waiting requests per model
        q.waiting_reqs.append(mqt.Req(rid=f"{n}{k}", arrival_time=now - k, slo=1.0, model=n, prompt_len=500, output_len=300))
    q._last_arrival_time = now - 1
    queues[n] = q; w[n] = {"model_size": 15.0}
with tempfile.TemporaryDirectory() as d:
    log = DecisionLog(os.path.join(d, "x.jsonl"))
    N = 2000
    t0 = time.perf_counter()
    for c in range(N):
        log.begin(now); log.gpu(0, 40.0, 0.0, 40.0, [])
        log.models(now, queues, insts, w, {f"model_{i}": now - 30 for i in range(1, 7)})
        for k in range(4): log.action("activate", "model_7", 0, "x")
        log.note("no_fit", "model_8", need_gb=16.0); log.end()
    dt = (time.perf_counter() - t0) / N
    size = os.path.getsize(os.path.join(d, "x.jsonl")) / N
print(f"per cycle: {dt*1000:.3f} ms, {size:.0f} bytes; share of a 5 s cycle: {dt/5:.5%}")
