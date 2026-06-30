# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from abc import ABC, abstractmethod

from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from ..models.route_decision import RouteDecision


class BaseModelRouter(ABC):
    """
    Architecture Building Block (ABB) for model routing.

    Implementations decide which model should handle
    a given inference request.
    """

    @abstractmethod
    def route(self, request: InferenceRequest) -> RouteDecision:
        """
        Select the best model for the request.
        """
        pass

    @abstractmethod
    def invoke(self, request: InferenceRequest) -> InferenceResponse:
        """
        Route the request and execute the inference (sync).
        """
        pass

    @abstractmethod
    async def ainvoke(self, request: InferenceRequest) -> InferenceResponse:
        """
        Route the request and execute the inference (async).
        """
        pass

    async def ainvoke_stream(self, request: InferenceRequest):
        """
        Route the request and stream the inference response incrementally.

        Optional capability — concrete (not abstract) so existing custom
        routers are unaffected. Default implementation falls back to
        ``ainvoke()`` and yields the complete output as a single chunk,
        so callers can always use the streaming interface uniformly even
        against a router/LLM pair that doesn't support true token-by-token
        streaming. Override (see ``K9ModelRouter``) for real streaming.

        Yields:
            str: Incremental text chunks.
        """
        response = await self.ainvoke(request)
        yield response.output