# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from ..models.route_decision import RouteDecision
from ..catalog.model_catalog import ModelCatalog
from .base_model_router import BaseModelRouter
import asyncio

from k9_aif_abb.k9_factories.llm_factory import LLMFactory


class K9ModelRouter(BaseModelRouter):

    def __init__(self, catalog: ModelCatalog):
        self.catalog = catalog

    def route(self, request: InferenceRequest) -> RouteDecision:

        alias = None

        # Capability routing
        if request.task_type:
            alias = self.catalog.find_by_capability(request.task_type)

        # Sensitivity routing
        if not alias and request.sensitivity == "confidential":
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
            rationale="K9 catalog-based routing"
        )

    def invoke(self, request: InferenceRequest) -> InferenceResponse:

        decision = self.route(request)

        model_info = self.catalog.get_model(decision.model_alias)

        llm_ref = model_info.get("llm_ref")

        # Get LLM from factory
        llm = LLMFactory.get(llm_ref)

        # Call the model

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
            provider=model_info.get("provider")
        )
    
    async def ainvoke(self, request: InferenceRequest) -> InferenceResponse:
        """
        Async inference path for agents/orchestrators.
        """
        decision = self.route(request)
        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)

        # Prefer async methods if available
        if hasattr(llm, "ainvoke") and callable(llm.ainvoke):
            result = await llm.ainvoke(request.prompt)

        elif hasattr(llm, "agenerate") and callable(llm.agenerate):
            result = await llm.agenerate(request.prompt)

        elif hasattr(llm, "generate") and callable(llm.generate):
            result = await llm.generate(request.prompt)

        # fallback to sync
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
            provider=model_info.get("provider")
        )