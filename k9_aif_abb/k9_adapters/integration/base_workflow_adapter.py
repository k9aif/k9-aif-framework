# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseWorkflowAdapter — ABB for workflow engine connectors
(Apache Airflow, AWS Step Functions, IBM BAW, Camunda, Prefect, Temporal).

On the K9X Studio canvas a Workflow Adapter can be reached directly from an
Orchestrator (synchronous trigger) or via a Messaging Adapter (async/event-driven).

Concrete SBBs implement trigger(); execute() is the fixed template.
Config keys: workflow_id, engine_url, wait_for_completion (default False).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional

from .base_integration_adapter import BaseIntegrationAdapter


class BaseWorkflowAdapter(BaseIntegrationAdapter):
    """ABB for deterministic workflow engine triggers — no LLM inference."""

    @abstractmethod
    def trigger(self, workflow_id: str, params: Dict[str, Any]) -> Any:
        """Trigger the workflow run. Return run ID or status from the engine."""

    def get_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Poll workflow run status. Override when wait_for_completion is needed."""
        return None

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        workflow_id = self.config.get("workflow_id") or payload.get("workflow_id", "")
        try:
            run_result = self.trigger(workflow_id, payload)
            return {
                "adapter":     self.adapter_name,
                "status":      "success",
                "workflow_id": workflow_id,
                "run":         run_result,
            }
        except Exception as exc:
            return self.handle_error(exc, payload)
