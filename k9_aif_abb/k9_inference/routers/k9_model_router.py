# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from ..models.route_decision import RouteDecision
from ..catalog.model_catalog import ModelCatalog
from .base_model_router import BaseModelRouter

from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_storage.postgres_database_storage import PostgresDatabaseStorage
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore


class K9ModelRouter(BaseModelRouter):
    """
    OOB K9 Model Router
    -------------------
    Catalog-based routing with session-aware persistence support.

    Current capabilities:
    - catalog-based model selection
    - PostgreSQL-backed session persistence
    - user turn persistence
    - routing decision persistence
    - model affinity persistence

    Future enhancements can add:
    - complexity scoring
    - governance scoring / DPL overrides
    - prefix hash tracking
    - summarization / context compression
    """

    def __init__(
        self,
        catalog: ModelCatalog,
        config: Optional[dict] = None,
        monitor=None,
        state_store: Optional[RoutingStateStore] = None,
    ):
        self.catalog = catalog
        self.config = config or {}
        self.monitor = monitor

        if state_store is not None:
            self.state_store = state_store
        else:
            self.db_storage = PostgresDatabaseStorage(config=self.config, monitor=monitor)
            self.state_store = RoutingStateStore(self.db_storage)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------
    def _resolve_session_id(self, request: InferenceRequest) -> str:
        session_id = getattr(request, "session_id", None)
        return str(session_id) if session_id else str(uuid.uuid4())

    def _resolve_user_id(self, request: InferenceRequest) -> str:
        user_id = getattr(request, "user_id", None)
        return str(user_id) if user_id else "anonymous"

    def _persist_request_context(self, request: InferenceRequest) -> tuple[str, str, int]:
        session_id = self._resolve_session_id(request)
        user_id = self._resolve_user_id(request)

        self.state_store.ensure_session(session_id=session_id, user_id=user_id)

        turn_id = self.state_store.append_turn(
            session_id=session_id,
            role="USER",
            content=request.prompt,
            token_count=None,
            compressed_flag=False,
        )

        return session_id, user_id, turn_id

    def _persist_route_decision(
        self,
        session_id: str,
        turn_id: int,
        decision: RouteDecision,
    ) -> None:
        self.state_store.record_routing_decision(
            session_id=session_id,
            turn_id=turn_id,
            selected_model=decision.model_alias,
            routing_reason=decision.rationale,
            complexity_score=None,
            governance_score=None,
            prompt_hash=None,
            metadata={
                "provider": decision.provider,
                "router": "K9ModelRouter",
            },
        )

        self.state_store.update_model_affinity(
            session_id=session_id,
            model_name=decision.model_alias,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def route(self, request: InferenceRequest) -> RouteDecision:
        alias = None

        # Capability routing
        if request.task_type:
            alias = self.catalog.find_by_capability(request.task_type)

        # Sensitivity routing
        if not alias and getattr(request, "sensitivity", None) == "confidential":
            alias = self.catalog.find_by_capability("confidential")

        # Fallback
        if not alias:
            alias = self.catalog.get_default_model()

        if not alias:
            raise RuntimeError("ModelRouter: no model alias resolved")

        model_info = self.catalog.get_model(alias)

        return RouteDecision(
            model_alias=alias,
            provider=model_info.get("provider"),
            rationale="K9 catalog-based routing",
        )

    # ------------------------------------------------------------------
    # Sync Invoke
    # ------------------------------------------------------------------
    def invoke(self, request: InferenceRequest) -> InferenceResponse:
        session_id, user_id, turn_id = self._persist_request_context(request)

        decision = self.route(request)
        self._persist_route_decision(session_id, turn_id, decision)

        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)

        if hasattr(llm, "invoke"):
            result = llm.invoke(request.prompt)
        elif hasattr(llm, "generate"):
            result = asyncio.run(llm.generate(request.prompt))
        elif hasattr(llm, "chat"):
            result = llm.chat(request.prompt)
        elif callable(llm):
            result = llm(request.prompt)
        else:
            raise AttributeError(
                f"{llm.__class__.__name__} has no supported inference method "
                "(expected invoke, generate, chat, or __call__)"
            )

        return InferenceResponse(
            output=result,
            model_alias=decision.model_alias,
            provider=model_info.get("provider"),
        )

    # ------------------------------------------------------------------
    # Async Invoke
    # ------------------------------------------------------------------
    async def ainvoke(self, request: InferenceRequest) -> InferenceResponse:
        session_id, user_id, turn_id = self._persist_request_context(request)

        decision = self.route(request)
        self._persist_route_decision(session_id, turn_id, decision)

        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)

        if hasattr(llm, "ainvoke") and callable(llm.ainvoke):
            result = await llm.ainvoke(request.prompt)

        elif hasattr(llm, "agenerate") and callable(llm.agenerate):
            result = await llm.agenerate(request.prompt)

        elif hasattr(llm, "generate") and callable(llm.generate):
            result = await llm.generate(request.prompt)

        elif hasattr(llm, "invoke") and callable(llm.invoke):
            result = llm.invoke(request.prompt)

        elif callable(llm):
            result = llm(request.prompt)

        else:
            raise AttributeError(
                f"{llm.__class__.__name__} has no supported inference method"
            )

        return InferenceResponse(
            output=str(result),
            model_alias=decision.model_alias,
            provider=model_info.get("provider"),
        )