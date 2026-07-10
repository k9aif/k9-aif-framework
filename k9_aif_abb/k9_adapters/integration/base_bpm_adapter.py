# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseBpmAdapter — ABB for BPM engine connectors
(Appian, Pega, Camunda, IBM BAW, Bizagi, Bonita).

Concrete SBBs implement start_process(); execute() is the fixed template.
Config keys: process_definition_key, engine_url, tenant_id.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional

from .base_integration_adapter import BaseIntegrationAdapter


class BaseBpmAdapter(BaseIntegrationAdapter):
    """ABB for deterministic BPM process invocations — no LLM inference."""

    @abstractmethod
    def start_process(self, process_key: str, variables: Dict[str, Any]) -> Any:
        """Start a BPM process instance. Return process instance ID or handle."""

    def get_task(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve current active task for a process instance. Override when needed."""
        return None

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        process_key = self.config.get("process_definition_key") or payload.get("process_key", "")
        try:
            instance = self.start_process(process_key, payload)
            return {
                "adapter":     self.adapter_name,
                "status":      "success",
                "process_key": process_key,
                "instance":    instance,
            }
        except Exception as exc:
            return self.handle_error(exc, payload)
