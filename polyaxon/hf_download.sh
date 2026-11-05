#!/bin/bash
# Download HF models (PRISM_HF_MODELS, space-separated ids) into the shared cluster cache, so the ovl_* steps find
# them with the image's HF_HUB_OFFLINE=1 (docker/prism/Dockerfile). F3, C10: Qwen2.5-14B/32B-Instruct (Apache-2.0,
# ungated: no token). Only weights/config/tokenizer files. Writes a listing to $PRISM_RESULTS/hf_download.txt.
set -uo pipefail
CACHE="${PRISM_HF_CACHE:-/scratch/hpc4ai/hf_cache}"
OUT="${PRISM_RESULTS:-/tmp}/hf_download.txt"
mkdir -p "$(dirname "$OUT")"
exec > >(tee -a "$OUT") 2>&1
echo "cache $CACHE; models: ${PRISM_HF_MODELS:-}"
touch "$CACHE/hub/.write_test_$$" && rm -f "$CACHE/hub/.write_test_$$" || { echo "CACHE NOT WRITABLE"; exit 1; }
df -h "$CACHE" | tail -1
rc=0
for m in ${PRISM_HF_MODELS:-}; do
  echo "---- $m $(date -u +%T)"
  HF_HOME="$CACHE" HF_HUB_OFFLINE=0 HF_HUB_DISABLE_PROGRESS_BARS=1 python3 - "$m" <<'PY' || rc=1
import sys
from huggingface_hub import snapshot_download
p = snapshot_download(sys.argv[1], allow_patterns=["*.json", "*.safetensors", "*.txt", "tokenizer*", "*.model"])
print("ok", p)
PY
  du -sh "$CACHE/hub/models--${m//\//--}" 2>/dev/null
done
# the cached copy must load offline, as the ovl_* steps use it
for m in ${PRISM_HF_MODELS:-}; do
  HF_HOME="$CACHE" HF_HUB_OFFLINE=1 python3 -c "import sys; from transformers import AutoConfig; c = AutoConfig.from_pretrained(sys.argv[1]); print('offline ok', sys.argv[1], c.architectures, c.num_hidden_layers)" "$m" || rc=1
done
echo "end rc=$rc $(date -u +%T)"
exit $rc
