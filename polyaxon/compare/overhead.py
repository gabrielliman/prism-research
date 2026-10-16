"""Latency of one model behind Prism's vLLM adapter vs. a plain `vllm serve` (same model and settings), to
measure the adapter's own overhead (Python step loop, Redis queues, request handler).

Usage: python3 polyaxon/compare/overhead.py {prism|vllm|sglang} <port> <model> <out.json>
  prism: Prism's /generate (either backend); vllm: `vllm serve` (OpenAI API); sglang: upstream SGLang's
  /generate (same format as Prism's, without the `model` field).
For concurrency 1, 8 and 32: 4 x concurrency streaming requests (fixed ~200-token prompt, 256 output
tokens, ignore_eos); records TTFT and inter-token latency per request (client side).
"""
import asyncio
import json
import statistics
import sys
import time

import aiohttp

MODE, PORT, MODEL, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
URL = f"http://127.0.0.1:{PORT}"
PROMPT = "Summarize the history of the Roman Empire, from its founding to its fall. " * 14
OUT_TOKENS = 256


async def one(session):
    if MODE in ("prism", "sglang"):
        url = f"{URL}/generate"
        payload = {"text": PROMPT, "stream": True,
                   "sampling_params": {"temperature": 0, "max_new_tokens": OUT_TOKENS, "ignore_eos": True}}
        if MODE == "prism":
            payload["model"] = MODEL
    else:
        url = f"{URL}/v1/completions"
        payload = {"model": MODEL, "prompt": PROMPT, "stream": True, "temperature": 0,
                   "max_tokens": OUT_TOKENS, "ignore_eos": True}
    st = time.perf_counter()
    stamps, last_len = [], 0
    async with session.post(url, json=payload) as r:
        async for raw in r.content:
            line = raw.strip()
            if not line.startswith(b"data: ") or line == b"data: [DONE]":
                continue
            d = json.loads(line[6:])
            # Prism streams the cumulative text; vLLM's OpenAI API streams deltas.
            cumulative = MODE in ("prism", "sglang")
            text = d.get("text") if cumulative else d["choices"][0].get("text", "")
            grew = len(text) > last_len if cumulative else bool(text)
            if grew:
                stamps.append(time.perf_counter())
                last_len = len(text) if cumulative else last_len
    itl = [b - a for a, b in zip(stamps, stamps[1:])]
    return {"ttft": stamps[0] - st if stamps else None, "itl_mean": statistics.mean(itl) if itl else None,
            "e2e": time.perf_counter() - st}


async def main():
    res = {}
    timeout = aiohttp.ClientTimeout(total=1800)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await one(session)  # warmup
        for conc in (1, 8, 32):
            sem = asyncio.Semaphore(conc)

            async def run():
                async with sem:
                    return await one(session)

            tic = time.perf_counter()
            outs = await asyncio.gather(*[run() for _ in range(4 * conc)])
            wall = time.perf_counter() - tic
            res[conc] = {
                "ttft_ms_median": 1000 * statistics.median(o["ttft"] for o in outs),
                "itl_ms_median": 1000 * statistics.median(o["itl_mean"] for o in outs),
                "out_tok_per_s": 4 * conc * OUT_TOKENS / wall,
            }
            print(MODE, conc, res[conc], flush=True)
    json.dump(res, open(OUT, "w"), indent=1)


asyncio.run(main())
