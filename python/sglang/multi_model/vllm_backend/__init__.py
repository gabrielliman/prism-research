"""vLLM backend for Prism (--engine-backend vllm).

An unmodified vLLM engine runs behind an adapter process that speaks the same protocol as the
Prism-modified SGLang scheduler (Redis generation queues, ZMQ control requests, per-model KV usage in
shared memory), so the request handler, GPU scheduler and global controller run unchanged. See
README_VLLM.md for what was adapted and what was not.

Keep this package free of top-level vllm/torch imports: the engine process sets CUDA_VISIBLE_DEVICES and
the kvcached environment before vLLM is imported.
"""
