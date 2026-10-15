#!/bin/bash
# Builds gabrielliman/prism:vllm0.30-kvcached0.1.6 from a minimal staged context (this repo's python/).
# Push with PUSH=1.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
IMAGE="${IMAGE:-gabrielliman/prism:vllm0.30-kvcached0.1.6}"

STAGE="$(mktemp -d /tmp/prism-docker-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
rsync -a --exclude __pycache__ --exclude '*.egg-info' "$REPO/python" "$STAGE"/
cp "$HERE/Dockerfile" "$STAGE"/
docker build -t "$IMAGE" "$STAGE"
if [ "${PUSH:-0}" = "1" ]; then docker push "$IMAGE"; fi
