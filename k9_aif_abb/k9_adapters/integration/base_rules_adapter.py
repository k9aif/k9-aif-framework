# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseRulesAdapter — ABB for business rules engine connectors
(Drools, IBM ODM, Corticon, OpenL Tablets, Easy Rules).

Concrete SBBs implement evaluate(); execute() is the fixed template.
Config keys: ruleset, engine_url, decision_service.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict

from .base_integration_adapter import BaseIntegrationAdapter


class BaseRulesAdapter(BaseIntegrationAdapter):
    """ABB for deterministic rules engine evaluation — no LLM inference."""

    @abstractmethod
    def evaluate(self, ruleset: str, facts: Dict[str, Any]) -> Any:
        """Submit facts to the rules engine and return the decision output."""

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        ruleset = self.config.get("ruleset") or payload.get("ruleset", "")
        try:
            decision = self.evaluate(ruleset, payload)
            return {"adapter": self.adapter_name, "status": "success", "decision": decision, "ruleset": ruleset}
        except Exception as exc:
            return self.handle_error(exc, payload)
