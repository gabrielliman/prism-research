# Prism with --engine-backend vllm, for Polyaxon/Axia.
# Base: kvcached's official vLLM image (kvcached v0.1.6 + vLLM v0.30.0, the pair kvcached tests), pinned by
# digest. The sglang code is uploaded with each job and reinstalled with `pip install -e python --no-deps`.
#
# Build from a staged context holding python/ (this repo):
#   docker/prism-vllm/build.sh
FROM ghcr.io/ovg-project/kvcached-vllm@sha256:88c433dad0324630c6651849ae512abb281c22bad8e491e0657fe3ba6204e19c
ENV DEBIAN_FRONTEND=noninteractive

# Same as docker/prism: a pod cannot `docker run redis`, and Prism needs redis >= 6.2 (`LPOP key count`).
ARG REDIS_VERSION=7.2.7
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl rsync \
 && rm -rf /var/lib/apt/lists/* \
 && cd /tmp && curl -fsSL https://download.redis.io/releases/redis-${REDIS_VERSION}.tar.gz | tar xz \
 && make -C redis-${REDIS_VERSION} -j"$(nproc)" BUILD_TLS=no \
 && make -C redis-${REDIS_VERSION} install PREFIX=/usr/local \
 && rm -rf /tmp/redis-${REDIS_VERSION}

# Prism's control plane (torch, vllm and kvcached are already in the base image).
COPY python /sgl-workspace/sglang-multi-model/python
RUN cd /sgl-workspace/sglang-multi-model && pip install --break-system-packages -e "python[vllm_backend]"

RUN pip list 2>/dev/null | grep -iE "^(sglang|vllm|torch|kvcached|transformers|redis) "

# The base image enables kvcached for every vLLM process under one IPC name; the Prism adapter sets
# ENABLE_KVCACHED and a per-instance KVCACHED_IPC_NAME itself (--enable-elastic-memory).
ENV ENABLE_KVCACHED=false \
    KVCACHED_IPC_NAME= \
    HF_HOME=/scratch/hpc4ai/hf_cache \
    HF_HUB_OFFLINE=1
WORKDIR /sgl-workspace/sglang-multi-model
ENTRYPOINT []
