"""How many kvcached-initialized processes fit on one GPU (run_examples.sh step kvcached_probe).

Each worker pool engine calls kvcached's init_kvcached(virtual_mem_size_gb, reserve_virtual_mem=True), which
reserves the virtual KV space and maps all of it to a zero page, 2 MB at a time. This starts processes one by
one, each doing that init and then waiting, and records the device memory after each, until one fails
(kvcached aborts) or --max is reached.

Usage: python3 polyaxon/kvcached_probe.py --virtual-gb 25 --max 20 [--no-reserve] --out probe.json
"""
import argparse
import json
import multiprocessing as mp
import subprocess
import time


def _child(virtual_gb, reserve, ready, stop):
    import torch
    from kvcached import ops as kvcached_ops

    torch.cuda.set_device(0)
    torch.zeros(1, device="cuda")  # CUDA context, as an engine has
    t = time.perf_counter()
    kvcached_ops.init_kvcached(gpu_id=0, virtual_mem_size_gb=virtual_gb, reserve_virtual_mem=reserve)
    ready.put(time.perf_counter() - t)
    stop.wait()


def _used_gb():
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"], text=True)
    return int(out.strip()) / 1024


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--virtual-gb", type=int, default=25)
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--no-reserve", action="store_true")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    ctx = mp.get_context("spawn")
    stop = ctx.Event()
    procs, rows = [], [{"processes": 0, "used_gb": _used_gb()}]
    print(f"virtual {a.virtual_gb} GB, reserve {not a.no_reserve}: 0 processes, {rows[0]['used_gb']:.2f} GB", flush=True)
    for k in range(1, a.max + 1):
        ready = ctx.Queue()
        proc = ctx.Process(target=_child, args=(a.virtual_gb, not a.no_reserve, ready, stop))
        proc.start()
        procs.append(proc)
        init_s = None
        while init_s is None and proc.is_alive():
            try:
                init_s = ready.get(timeout=1)
            except Exception:
                pass
        row = {"processes": k, "ok": init_s is not None, "init_s": init_s, "used_gb": _used_gb(),
               "exitcode": proc.exitcode}
        rows.append(row)
        print(row, flush=True)
        if init_s is None:
            break
    stop.set()
    for proc in procs:
        proc.join(timeout=30)
    json.dump({"virtual_gb": a.virtual_gb, "reserve": not a.no_reserve, "rows": rows}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
