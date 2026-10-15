"""Conversions between SGLang's request format (used by Prism's frontend and benchmark) and vLLM's."""

from typing import Optional


def to_vllm_sampling_params(params: Optional[dict], max_model_len: int, prompt_len: int):
    """SGLang sampling_params dict (GenerateReqInput.sampling_params) -> vllm.SamplingParams.

    Mirrors sglang.srt.sampling.sampling_params.SamplingParams and Scheduler.handle_generate_request:
    max_new_tokens defaults to 128 and is capped by the context length; temperature 0 means greedy.
    """
    from vllm import SamplingParams
    from vllm.sampling_params import RequestOutputKind, StructuredOutputsParams

    p = dict(params or {})
    if p.get("n", 1) != 1:
        # The request handler splits parallel sampling into single requests before they reach an engine.
        raise ValueError("n > 1 is not supported by the vLLM backend")
    max_new_tokens = p.get("max_new_tokens", 128)
    if max_new_tokens is None:
        max_new_tokens = 1 << 30
    max_new_tokens = min(max_new_tokens, max_model_len - prompt_len - 1)

    structured = None
    if p.get("json_schema") is not None:
        structured = StructuredOutputsParams(json=p["json_schema"])
    elif p.get("regex") is not None:
        structured = StructuredOutputsParams(regex=p["regex"])

    top_k = p.get("top_k", -1)
    return SamplingParams(
        max_tokens=max(max_new_tokens, 0),
        min_tokens=p.get("min_new_tokens", 0),
        temperature=p.get("temperature", 1.0),
        top_p=p.get("top_p", 1.0),
        top_k=0 if top_k is None or top_k < 0 or top_k >= (1 << 30) else top_k,
        min_p=p.get("min_p", 0.0),
        frequency_penalty=p.get("frequency_penalty", 0.0),
        presence_penalty=p.get("presence_penalty", 0.0),
        repetition_penalty=p.get("repetition_penalty", 1.0),
        stop=p.get("stop") or None,
        stop_token_ids=list(p["stop_token_ids"]) if p.get("stop_token_ids") else None,
        ignore_eos=p.get("ignore_eos", False),
        skip_special_tokens=p.get("skip_special_tokens", True),
        spaces_between_special_tokens=p.get("spaces_between_special_tokens", True),
        # SGLang trims the matched stop string unless no_stop_trim.
        include_stop_str_in_output=p.get("no_stop_trim", False),
        structured_outputs=structured,
        output_kind=RequestOutputKind.CUMULATIVE,
    )


def finish_reason_json(completion, num_output_tokens: int) -> Optional[dict]:
    """vLLM CompletionOutput finish info -> SGLang BaseFinishReason.to_json() format."""
    reason = completion.finish_reason
    if reason is None:
        return None
    if reason == "length":
        return {"type": "length", "length": num_output_tokens}
    if reason == "stop":
        # stop_reason is the matched stop string or stop token id; None means EOS.
        matched = completion.stop_reason
        if matched is None and completion.token_ids:
            matched = completion.token_ids[-1]
        return {"type": "stop", "matched": matched}
    return {"type": "abort"}
