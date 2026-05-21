# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — EOCModelRouter (SBB)
#
# Extends K9ModelRouter with EOC-specific routing dimensions:
#   - Task type → model capability mapping
#   - Cost profile (premium/standard/minimal)
#   - Latency budget (realtime/interactive/batch)
#   - Compliance hard-requirements (Guardian for PII/policy tasks)

import logging
import time
from typing import Any, Callable, Dict, Optional

from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse
from k9_aif_abb.k9_inference.models.route_decision import RouteDecision
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter
from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore

log = logging.getLogger(__name__)

# SSE callback registered by api/app.py at startup.
_sse_callback: Optional[Callable[[Dict[str, Any]], None]] = None


def register_sse_callback(fn: Callable[[Dict[str, Any]], None]) -> None:
    global _sse_callback
    _sse_callback = fn
    log.info("[EOCModelRouter] SSE callback registered")


# Tasks that MUST route to Guardian — no fallback accepted.
GUARDIAN_REQUIRED_TASKS = {
    "pii_detection",
    "policy",
    "confidential",
    "guardrails",
    "output_validation",
}

# Cost-profile preference ordering (cheapest first for cost-sensitive tasks).
COST_SENSITIVE_TASKS = {
    "summarization",
    "general",
    "chat",
    "customer_intent",
}


class EOCModelRouter(K9ModelRouter):
    """
    EOC Model Router — SBB extending K9ModelRouter.

    Routing decision matrix:
      Task Type                  Primary Model    Fallback      Rationale
      ─────────────────────────  ───────────────  ────────────  ─────────────────────────────
      adjudication / reasoning   reasoning        general       Domain-specific, high accuracy
      pii_detection / policy     guardian         NONE (hard)   Regulatory; no fallback
      extraction / ocr           extraction       general       Structured output required
      fraud / anomaly            reasoning        general       Complex signal correlation
      customer_intent / chat     general          reasoning     High-volume; cost-optimized
      audit_report               reasoning        general       Formal language; accuracy
      summarization              general          —             Commodity; minimize cost
    """

    def __init__(
        self,
        catalog: ModelCatalog,
        config: Optional[dict] = None,
        monitor=None,
        state_store: Optional[RoutingStateStore] = None,
    ):
        super().__init__(catalog=catalog, config=config, monitor=monitor, state_store=state_store)

    # ------------------------------------------------------------------
    def invoke(self, request: InferenceRequest) -> InferenceResponse:
        t0 = time.monotonic()
        resp = super().invoke(request)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if not resp.output or resp.output.startswith("[WARN]"):
            raise RuntimeError(
                f"LLM backend unavailable (agent={( request.metadata or {}).get('agent','?')} "
                f"model={resp.model_alias}): {resp.output}"
            )

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
                log.warning("[EOCModelRouter] SSE push failed: %s", exc)

        return resp

    # ------------------------------------------------------------------
    def route(self, request: InferenceRequest) -> RouteDecision:
        task = (request.task_type or "").lower()

        # 1. Hard compliance gate — Guardian required, no fallback.
        if task in GUARDIAN_REQUIRED_TASKS or getattr(request, "sensitivity", None) == "confidential":
            alias = self.catalog.find_by_capability("guardrails")
            if alias:
                return RouteDecision(
                    model_alias=alias,
                    provider=self.catalog.get_model(alias).get("provider"),
                    rationale="EOC compliance gate: Guardian required for this task — no fallback",
                )

        # 2. Cost-sensitive tasks → prefer cheapest capable model.
        if task in COST_SENSITIVE_TASKS:
            alias = self.catalog.find_by_capability(task)
            if not alias:
                alias = self.catalog.find_by_capability("general")
            if alias:
                return RouteDecision(
                    model_alias=alias,
                    provider=self.catalog.get_model(alias).get("provider"),
                    rationale=f"EOC cost-optimized routing: task={task}",
                )

        # 3. Capability-matched routing (reasoning, extraction, etc.).
        if task:
            alias = self.catalog.find_by_capability(task)
            if alias:
                return RouteDecision(
                    model_alias=alias,
                    provider=self.catalog.get_model(alias).get("provider"),
                    rationale=f"EOC capability routing: task={task} → {alias}",
                )

        # 4. Fallback to catalog default.
        alias = self.catalog.get_default_model()
        if not alias:
            raise RuntimeError("EOCModelRouter: no model alias could be resolved")

        return RouteDecision(
            model_alias=alias,
            provider=self.catalog.get_model(alias).get("provider"),
            rationale="EOC fallback: default catalog model",
        )
