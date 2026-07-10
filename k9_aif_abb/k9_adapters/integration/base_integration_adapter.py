# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseIntegrationAdapter — ABB contract for all K9-AIF integration adapters.

Integration adapters are deterministic, non-agentic connectors to external
enterprise systems (APIs, message buses, rules engines, workflow engines,
integration platforms, data stores). They belong on the canvas between an
Orchestrator and the external system — no LLM inference involved.

SA extension pattern:
    class MyApiConnector(BaseApiAdapter):
        def call_endpoint(self, url, method, headers, body): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseIntegrationAdapter(ABC):
    """
    Abstract base for all K9-AIF integration adapters.

    Subclasses must implement :meth:`execute`. Each specific adapter ABB
    (BaseApiAdapter, BaseMessagingAdapter, etc.) provides a template
    implementation of execute() that delegates to a type-specific abstract
    method, so concrete SBBs only implement that one method.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self.adapter_name: str = self.__class__.__name__

    @abstractmethod
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke the external system and return a K9-AIF-normalised dict."""

    def validate_input(self, payload: Dict[str, Any]) -> None:
        """Override to enforce required fields. Raise ValueError on invalid input."""

    def handle_error(self, exc: Exception, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Default error handler — returns structured error dict, never raises."""
        return {
            "adapter": self.adapter_name,
            "status": "error",
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
