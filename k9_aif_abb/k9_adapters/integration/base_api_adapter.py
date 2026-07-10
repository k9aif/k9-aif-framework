# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseApiAdapter — ABB for REST/SOAP/GraphQL API connectors.

Concrete SBBs implement call_endpoint(); execute() is the fixed template.
Config keys: url, method (default POST), headers, timeout (default 30).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional

from .base_integration_adapter import BaseIntegrationAdapter


class BaseApiAdapter(BaseIntegrationAdapter):
    """ABB for deterministic HTTP/API calls — no LLM inference."""

    @abstractmethod
    def call_endpoint(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> Any:
        """Execute the HTTP call. Return raw response (SA decides the shape)."""

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        url     = self.config.get("url", payload.get("url", ""))
        method  = self.config.get("method", "POST").upper()
        headers = {**self.config.get("headers", {}), **payload.get("headers", {})}
        try:
            result = self.call_endpoint(url, method, headers, payload)
            return {"adapter": self.adapter_name, "status": "success", "result": result}
        except Exception as exc:
            return self.handle_error(exc, payload)
