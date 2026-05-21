# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/llm_invoke.py
#
# Thin wrapper around ModelRouterFactory.get_router().invoke() that:
#   1. Raises RuntimeError if the LLM backend is unreachable ([WARN] response).
#   2. Publishes an LLMCall SSE event via the registered callback (optional).
#
# Usage in agents:
#   from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
#   resp = llm_invoke(self.config, req)

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse

log = logging.getLogger(__name__)

# Optional SSE push callback — registered by api/app.py at startup.
# Signature: (event: dict) -> None
_sse_callback: Optional[Callable[[Dict[str, Any]], None]] = None


def register_sse_callback(fn: Callable[[Dict[str, Any]], None]) -> None:
    """Called once from api/app.py lifespan to wire up the SSE push."""
    global _sse_callback
    _sse_callback = fn
    log.info("[llm_invoke] SSE callback registered")


def llm_invoke(config: Dict[str, Any], request: InferenceRequest) -> InferenceResponse:
    """
    Invoke the LLM router and return the response.

    Raises:
        RuntimeError: if the LLM backend is unreachable or returns an empty response.
    """
    import time
    router = ModelRouterFactory.get_router(config)
    t0 = time.monotonic()
    resp = router.invoke(request)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # OllamaLLM silently returns "[WARN]..." on connection failure — fail hard.
    if not resp.output or resp.output.startswith("[WARN]"):
        raise RuntimeError(
            f"LLM backend unavailable (agent={( request.metadata or {}).get('agent','?')} "
            f"model={resp.model_alias}): {resp.output}"
        )

    # Push SSE trace event if the callback is wired.
    if _sse_callback is not None:
        try:
            tokens = (resp.token_usage or {}) if resp.token_usage else {}
            _sse_callback({
                "type":       "LLMCall",
                "agent":      (request.metadata or {}).get("agent", "unknown"),
                "task_type":  request.task_type or "general",
                "model":      resp.model_alias or "?",
                "provider":   resp.provider or "ollama",
                "latency_ms": resp.latency_ms or elapsed_ms,
                "tokens_in":  tokens.get("prompt", tokens.get("input")),
                "tokens_out": tokens.get("completion", tokens.get("output")),
            })
        except Exception as exc:
            log.warning("[llm_invoke] SSE push failed: %s", exc)

    log.info("[llm_invoke] agent=%s task=%s model=%s latency_ms=%d",
             (request.metadata or {}).get("agent", "?"), request.task_type,
             resp.model_alias, elapsed_ms)
    return resp
