# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseProcessFlowAdapter — ABB for integration platform connectors
(MuleSoft, TIBCO, IBM App Connect, WSO2, Boomi, Azure Logic Apps).

Concrete SBBs implement invoke(); execute() is the fixed template.
Config keys: flow_id, platform_url, correlation_id_field.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict

from .base_integration_adapter import BaseIntegrationAdapter


class BaseProcessFlowAdapter(BaseIntegrationAdapter):
    """ABB for deterministic integration platform invocations — no LLM inference."""

    @abstractmethod
    def invoke(self, flow_id: str, payload: Dict[str, Any]) -> Any:
        """Invoke the integration flow and return the platform response."""

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        flow_id = self.config.get("flow_id") or payload.get("flow_id", "")
        try:
            response = self.invoke(flow_id, payload)
            return {
                "adapter": self.adapter_name,
                "status":  "success",
                "flow_id": flow_id,
                "result":  response,
            }
        except Exception as exc:
            return self.handle_error(exc, payload)
