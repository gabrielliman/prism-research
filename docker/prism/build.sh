#!/bin/bash
# Builds gabrielliman/prism:sglang0.3.4-cu121 from a minimal staged context
# (this repo's python/ + kvcached prism/shm). Push with PUSH=1.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KVCACHED="${KVCACHED:-$(dirname "$REPO")/kvcached}"
IMAGE="${IMAGE:-gabrielliman/prism:sglang0.3.4-cu121}"

[ -d "$KVCACHED" ] || git clone -b prism/shm https://github.com/ovg-project/kvcached.git "$KVCACHED"
STAGE="$(mktemp -d /tmp/prism-docker-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
rsync -a --exclude __pycache__ --exclude '*.egg-info' "$REPO/python" "$STAGE"/
rsync -a --exclude .git --exclude build --exclude '*.so' "$KVCACHED/" "$STAGE/kvcached/"
cp "$HERE/Dockerfile" "$STAGE"/
echo "kvcached $(git -C "$KVCACHED" rev-parse --short HEAD) ($(git -C "$KVCACHED" branch --show-current))"
docker build -t "$IMAGE" "$STAGE"
if [ "${PUSH:-0}" = "1" ]; then docker push "$IMAGE"; fi
