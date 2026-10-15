"""Sends the same fixed requests to a running 2-model Prism server and saves the responses, so that the
SGLang and vLLM backends can be compared (compare/report.py).

Usage: python3 polyaxon/compare/parity.py <port> <out.json>
"""
import json
import sys
import time

import requests

URL = f"http://127.0.0.1:{sys.argv[1]}"
PROMPTS = [
    "The history of the city of Rome begins",
    "Explain in one paragraph how a transformer language model works.",
    "Write a Python function that returns the n-th Fibonacci number.",
    "List three differences between TCP and UDP.",
    "The capital city of France is",
    "Translate to Portuguese: The weather is nice today.",
    "Once upon a time, in a small village,",
    "What is 17 multiplied by 23?",
]
# (case name, sampling_params): each exercises one SGLang sampling feature the backends must map.
CASES = [
    ("greedy_64", {"temperature": 0, "max_new_tokens": 64}),
    ("greedy_eos", {"temperature": 0, "max_new_tokens": 256}),
    ("one_token", {"temperature": 0, "max_new_tokens": 1}),
    ("stop_str", {"temperature": 0, "max_new_tokens": 128, "stop": ["."]}),
    ("stop_str_no_trim", {"temperature": 0, "max_new_tokens": 128, "stop": ["."], "no_stop_trim": True}),
    ("min_tokens", {"temperature": 0, "max_new_tokens": 64, "min_new_tokens": 32, "stop": ["."]}),
    ("ignore_eos", {"temperature": 0, "max_new_tokens": 96, "ignore_eos": True}),
    ("regex_digits", {"temperature": 0, "max_new_tokens": 16, "regex": "[0-9]{1,6}"}),
    ("top_k1_sampling", {"temperature": 0.8, "top_k": 1, "max_new_tokens": 48}),
    ("repetition_penalty", {"temperature": 0, "max_new_tokens": 64, "repetition_penalty": 1.3}),
]

results = []
for model in ("model_1", "model_2"):
    for case, params in CASES:
        for prompt in PROMPTS:
            tic = time.time()
            try:
                r = requests.post(
                    f"{URL}/generate",
                    json={"text": prompt, "model": model, "sampling_params": params},
                    timeout=300,
                )
                body = r.json() if r.status_code == 200 else {"error": r.text[:500]}
                status = r.status_code
            except Exception as e:
                body, status = {"error": repr(e)}, None
            results.append(
                {"model": model, "case": case, "prompt": prompt, "params": params, "status": status,
                 "latency": time.time() - tic, "response": body}
            )
        print(f"{model} {case}: {sum(1 for x in results if x['case'] == case and x['model'] == model and x['status'] == 200)}/{len(PROMPTS)} ok", flush=True)
json.dump(results, open(sys.argv[2], "w"), indent=1)
