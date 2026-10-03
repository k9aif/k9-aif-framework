# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9_utils/llm_invoke.py
#
# Framework-level LLM invocation utility.
#
# Thin wrapper around ModelRouterFactory.get_router().invoke() that:
#   1. Raises RuntimeError if the LLM backend is unreachable ([WARN] response).
#   2. Publishes an LLMCall trace event via an optional registered callback
#      (e.g. SSE push, metrics sink — wired in by the application at startup).
#
# Usage in agents:
#   from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
#   resp = llm_invoke(self.config, req)
#
# Optional callback registration (call once at app startup):
#   from k9_aif_abb.k9_utils.llm_invoke import register_trace_callback
#   register_trace_callback(my_push_fn)

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse
from k9_aif_abb.k9_utils.trace_events import register_trace_callback, emit_trace_event
from k9_aif_abb.k9_core.governance.call_context import inside_governed_call
from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance, assert_governed, governance_from_config


def _resolve_sync(value: Any) -> Any:
    """Governance backends may be sync or async; run an awaitable to completion."""
    import inspect
    if not inspect.isawaitable(value):
        return value
    import asyncio
    import concurrent.futures

    async def _await():
        return await value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _await()).result()

log = logging.getLogger(__name__)

# register_trace_callback/emit_trace_event now live in trace_events.py (a
# shared bus also used by ShieldGovernance/GuardianGovernance/apply_zero_trust)
# — re-exported here for backward compatibility with existing callers doing
# `from k9_aif_abb.k9_utils.llm_invoke import register_trace_callback`.
__all__ = ["register_trace_callback", "emit_trace_event", "llm_invoke", "llm_invoke_stream"]


def _call_governance(config: Dict[str, Any], request: InferenceRequest):
    """Governance for a model call made outside a governed entry point (an
    agent's execute()/execute_stream() or an adapter's execute_flow()), or
    None when the caller already governs it. Built from the same
    ``security.shield`` config the agents use; refused in production when
    none is configured."""
    if inside_governed_call():
        return None
    governance = governance_from_config(config)
    agent = (request.metadata or {}).get("agent", "?")
    assert_governed(governance or NoopGovernance(), f"llm_invoke(agent={agent})", log)
    return governance


def _gov_ctx(request: InferenceRequest) -> Dict[str, Any]:
    return {"layer": "llm_invoke", "component": (request.metadata or {}).get("agent", "?"),
            "component_type": "model_call"}


def _check_request(governance, request: InferenceRequest) -> InferenceRequest:
    payload = {"prompt": request.prompt, "system_prompt": request.system_prompt}
    checked = _resolve_sync(governance.pre_process(payload, _gov_ctx(request)))
    if isinstance(checked, dict) and checked.get("prompt") is not None and checked["prompt"] != request.prompt:
        request = request.model_copy(update={"prompt": checked["prompt"]}) if hasattr(request, "model_copy") else request
    return request


def _check_output(governance, request: InferenceRequest, output: str) -> str:
    checked = _resolve_sync(governance.post_process(output, _gov_ctx(request)))
    return checked if isinstance(checked, str) else output


def llm_invoke(
    config: Dict[str, Any],
    request: InferenceRequest,
    max_retries: int = 3,
    retry_delay_s: float = 60.0,
) -> InferenceResponse:
    """
    Invoke the LLM router and return the response.

    Retries up to ``max_retries`` times (default 3, ``retry_delay_s`` seconds
    apart, default 60s) on a failed/empty response before raising. A failed
    call here is often just an unlucky sample -- e.g. a hybrid-reasoning
    model spending its whole token budget on invisible "thinking" and
    returning zero real output on one attempt -- so retrying the identical
    request can succeed outright with no other change. Caught live in DAS
    production: OllamaLLM logged "Ollama responded (0 chars)" after 19s of
    genuine GPU work, which this function turned into a hard failure that
    took down the whole job with no retry at all.

    Args:
        config:  Application config dict (must contain ``inference`` section).
        request: :class:`InferenceRequest` describing the prompt and task type.
        max_retries: total attempts before giving up (1 = no retry).
        retry_delay_s: seconds to wait between attempts.

    Returns:
        :class:`InferenceResponse` with model output and metadata.

    Raises:
        RuntimeError: if every attempt is unreachable or returns an empty
            response (OllamaLLM signals this with a ``[WARN]`` prefix).
    """
    # Governance and audit for every inference call: inside an agent or adapter
    # flow its own checks cover this call; anywhere else they run here.
    governance = _call_governance(config, request)
    if governance is not None:
        request = _check_request(governance, request)

    router = ModelRouterFactory.get_router(config)
    agent = (request.metadata or {}).get("agent", "?")

    resp = None
    last_error: Optional[Exception] = None
    t0 = time.monotonic()
    for attempt in range(1, max(1, max_retries) + 1):
        last_error = None
        try:
            resp = router.invoke(request)
        except Exception as exc:
            last_error = exc
            resp = None

        if resp is not None and resp.output and not resp.output.startswith("[WARN]"):
            break

        if attempt < max_retries:
            log.warning(
                "[llm_invoke] attempt %d/%d failed (agent=%s): %s -- retrying in %.0fs",
                attempt, max_retries, agent,
                last_error if last_error else getattr(resp, "output", "empty response"),
                retry_delay_s,
            )
            time.sleep(retry_delay_s)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if last_error is not None:
        raise RuntimeError(
            f"LLM backend unavailable (agent={agent}) after {max_retries} attempt(s): {last_error}"
        )
    # OllamaLLM signals a failure by returning a "[WARN]..." string rather
    # than raising -- fail hard once retries are exhausted.
    if not resp.output or resp.output.startswith("[WARN]"):
        raise RuntimeError(
            f"LLM backend unavailable "
            f"(agent={agent} "
            f"model={resp.model_alias}) after {max_retries} attempt(s): {resp.output}"
        )

    tokens = (resp.token_usage or {}) if resp.token_usage else {}
    # resp.model_alias is the router's catalog key (e.g. "reasoning"), not the
    # literal model name — resolve the real model string from config so the
    # trace event says "granite3-dense:8b", not just "reasoning".
    model_catalog = config.get("inference", {}).get("llm_factory", {}).get("models", {})
    catalog_entry = model_catalog.get(resp.model_alias) if resp.model_alias else None
    if isinstance(catalog_entry, dict):
        real_model = catalog_entry.get("model")
    elif isinstance(catalog_entry, str):
        real_model = catalog_entry
    else:
        real_model = None
    emit_trace_event({
        "type":       "LLMCall",
        "agent":      (request.metadata or {}).get("agent", "unknown"),
        "task_type":  request.task_type or "general",
        "model":      real_model or resp.model_alias or "?",
        "model_alias": resp.model_alias,
        "provider":   resp.provider or "unknown",
        "latency_ms": resp.latency_ms or elapsed_ms,
        "tokens_in":  tokens.get("prompt", tokens.get("input")),
        "tokens_out": tokens.get("completion", tokens.get("output")),
    })

    log.info(
        "[llm_invoke] agent=%s task=%s model=%s latency_ms=%d",
        (request.metadata or {}).get("agent", "?"),
        request.task_type,
        resp.model_alias,
        elapsed_ms,
    )
    if governance is not None:
        resp.output = _check_output(governance, request, resp.output)
    return resp


async def llm_invoke_stream(config: Dict[str, Any], request: InferenceRequest):
    """
    Invoke the LLM router and yield the response incrementally.

    Streaming counterpart to :func:`llm_invoke`. Use when the caller wants
    to forward text to a UI as it's generated (chat, live console) rather
    than waiting for the complete response.

    Args:
        config:  Application config dict (must contain ``inference`` section).
        request: :class:`InferenceRequest` describing the prompt and task type.

    Yields:
        str: Incremental text chunks. If the underlying router/LLM doesn't
            support true streaming, yields the complete response as a single
            chunk — callers can always use this interface uniformly.

    Note:
        Unlike :func:`llm_invoke`, this does not raise on ``[WARN]``-prefixed
        output — streaming callers typically render chunks as they arrive
        and should check the accumulated text themselves if hard failure
        detection is needed.
    """
    # Same rule as llm_invoke(): governed here unless the caller already is.
    # The request is checked before the first chunk, the complete reply at the
    # end (a streamed reply blocked at egress has already been sent).
    governance = _call_governance(config, request)
    if governance is not None:
        request = _check_request(governance, request)

    router = ModelRouterFactory.get_router(config)
    t0 = time.monotonic()
    full_output = []

    async for chunk in router.ainvoke_stream(request):
        full_output.append(chunk)
        yield chunk

    if governance is not None:
        _check_output(governance, request, "".join(str(c) for c in full_output))

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    emit_trace_event({
        "type":       "LLMCall",
        "agent":      (request.metadata or {}).get("agent", "unknown"),
        "task_type":  request.task_type or "general",
        "model":      request.metadata.get("model_alias") if request.metadata else None,
        "latency_ms": elapsed_ms,
        "streamed":   True,
    })

    log.info(
        "[llm_invoke_stream] agent=%s task=%s latency_ms=%d chunks=%d",
        (request.metadata or {}).get("agent", "?"),
        request.task_type,
        elapsed_ms,
        len(full_output),
    )
