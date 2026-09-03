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
from typing import Any, Callable, Dict, Optional

from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse

log = logging.getLogger(__name__)

# Optional trace callback — registered by the application at startup.
# Signature: (event: dict) -> None
_trace_callback: Optional[Callable[[Dict[str, Any]], None]] = None


def register_trace_callback(fn: Callable[[Dict[str, Any]], None]) -> None:
    """
    Register a callback that receives an LLMCall event dict after every
    successful invocation.  Call once at application startup.

    The callback is fire-and-forget: exceptions are caught and logged so
    a failing callback never breaks agent execution.
    """
    global _trace_callback
    _trace_callback = fn
    log.info("[llm_invoke] trace callback registered: %s", fn)


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

    if _trace_callback is not None:
        try:
            tokens = (resp.token_usage or {}) if resp.token_usage else {}
            _trace_callback({
                "type":       "LLMCall",
                "agent":      (request.metadata or {}).get("agent", "unknown"),
                "task_type":  request.task_type or "general",
                "model":      resp.model_alias or "?",
                "provider":   resp.provider or "unknown",
                "latency_ms": resp.latency_ms or elapsed_ms,
                "tokens_in":  tokens.get("prompt", tokens.get("input")),
                "tokens_out": tokens.get("completion", tokens.get("output")),
            })
        except Exception as exc:
            log.warning("[llm_invoke] trace callback failed: %s", exc)

    log.info(
        "[llm_invoke] agent=%s task=%s model=%s latency_ms=%d",
        (request.metadata or {}).get("agent", "?"),
        request.task_type,
        resp.model_alias,
        elapsed_ms,
    )
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
    router = ModelRouterFactory.get_router(config)
    t0 = time.monotonic()
    full_output = []

    async for chunk in router.ainvoke_stream(request):
        full_output.append(chunk)
        yield chunk

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if _trace_callback is not None:
        try:
            _trace_callback({
                "type":       "LLMCall",
                "agent":      (request.metadata or {}).get("agent", "unknown"),
                "task_type":  request.task_type or "general",
                "model":      request.metadata.get("model_alias") if request.metadata else None,
                "latency_ms": elapsed_ms,
                "streamed":   True,
            })
        except Exception as exc:
            log.warning("[llm_invoke_stream] trace callback failed: %s", exc)

    log.info(
        "[llm_invoke_stream] agent=%s task=%s latency_ms=%d chunks=%d",
        (request.metadata or {}).get("agent", "?"),
        request.task_type,
        elapsed_ms,
        len(full_output),
    )
