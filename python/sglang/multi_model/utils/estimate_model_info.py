"""Estimate a model_info.json entry without loading the model (no GPU, no vLLM 0.6 loader).

profile_model_info.py measures the GPU memory of a model loaded with SGLang 0.3.4's vLLM (0.6.3) and
does not run with the vLLM backend's environment. This estimates the same two fields from the checkpoint:
  model_size: bytes of the safetensors weights, in GiB (the profiled values match it within ~1%);
  cell_size:  KV bytes per token, num_kv_heads * head_dim * num_layers * 2 * dtype bytes (same formula as
              profile_model_info.get_cell_size).

Usage: python3 -m sglang.multi_model.utils.estimate_model_info <model_path>... [--write]
  --write adds the missing models to model_info.json next to this file.
"""

import glob
import json
import os
import sys

import torch
from huggingface_hub import snapshot_download
from transformers import AutoConfig

MODEL_INFO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_info.json")


def estimate(model_path: str) -> dict:
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    config = getattr(config, "text_config", config)
    local = model_path if os.path.isdir(model_path) else snapshot_download(
        model_path, allow_patterns=["*.safetensors", "*.json"]
    )
    weights = sum(os.path.getsize(f) for f in glob.glob(os.path.join(local, "*.safetensors")))
    if weights == 0:
        raise ValueError(f"No safetensors weights found for {model_path}")

    num_kv_heads = getattr(config, "num_key_value_heads", None) or config.num_attention_heads
    head_dim = getattr(config, "head_dim", None) or config.hidden_size // config.num_attention_heads
    dtype = getattr(config, "torch_dtype", None) or getattr(config, "dtype", None) or torch.float16
    if isinstance(dtype, str):
        dtype = getattr(torch, dtype)
    if dtype == torch.float32:
        dtype = torch.float16  # "auto" serves float32 checkpoints in float16
    cell_size = num_kv_heads * head_dim * config.num_hidden_layers * 2 * dtype.itemsize
    return {"model_size": weights / (1 << 30), "cell_size": cell_size}


if __name__ == "__main__":
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    with open(MODEL_INFO_PATH) as f:
        model_info = json.load(f)
    for path in paths:
        if path in model_info:
            print(path, "already in model_info.json:", model_info[path])
            continue
        model_info[path] = estimate(path)
        print(path, "estimated:", model_info[path])
    if "--write" in sys.argv:
        with open(MODEL_INFO_PATH, "w") as f:
            json.dump(model_info, f)
