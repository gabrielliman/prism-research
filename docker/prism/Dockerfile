# Prism image for Polyaxon/Axia: the container from install.md with the install steps baked in.
# The sglang code is uploaded with each job and reinstalled with `pip install -e python --no-deps`.
#
# Build from a staged context holding python/ (this repo) and kvcached/ (prism/shm branch):
#   docker/prism/build.sh
FROM lmsysorg/sglang:v0.3.4.post2-cu121
ENV DEBIAN_FRONTEND=noninteractive

# install.md runs redis in its own container (`docker run redis`); a pod can't, so build redis-server
# here. Prism needs redis >= 6.2 (`LPOP key count`); Ubuntu 20.04 only has 5.0, and the official
# redis 7 binaries need libssl3. Built from the official source tarball without TLS.
ARG REDIS_VERSION=7.2.7
RUN cd /tmp && curl -fsSL https://download.redis.io/releases/redis-${REDIS_VERSION}.tar.gz | tar xz \
 && make -C redis-${REDIS_VERSION} -j"$(nproc)" BUILD_TLS=no \
 && make -C redis-${REDIS_VERSION} install PREFIX=/usr/local \
 && rm -rf /tmp/redis-${REDIS_VERSION}

# install.md: install sglang-multi-model
COPY python /sgl-workspace/sglang-multi-model/python
RUN cd /sgl-workspace/sglang-multi-model && pip install -e "python[all]"

# install.md: install kvcached. It links against libcuda, which only exists at runtime with a GPU,
# so link against the CUDA driver stub while building.
COPY kvcached /sgl-workspace/kvcached
RUN cd /sgl-workspace/kvcached \
 && ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1 \
 && export LIBRARY_PATH=/usr/local/cuda/lib64/stubs TORCH_CUDA_ARCH_LIST="8.9;9.0" \
 && pip install -e . --no-build-isolation \
 && python3 setup.py build_ext --inplace \
 && rm -f /usr/local/cuda/lib64/stubs/libcuda.so.1

RUN pip list 2>/dev/null | grep -iE "^(sglang|vllm|torch|flashinfer|kvcached|transformers|redis) "

ENV HF_HOME=/scratch/hpc4ai/hf_cache \
    HF_HUB_OFFLINE=1
WORKDIR /sgl-workspace/sglang-multi-model
