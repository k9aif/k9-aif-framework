# SPDX-License-Identifier: Apache-2.0
"""
SBB override example 2 — AcmeIntentOrchestrator

Demonstrates: override execute_flow to add domain-specific
pre-processing and a custom clarification message.

SBBs override IntentOrchestrator.execute_flow() when they need to
add logic around the classification — enrichment, audit trail,
domain-specific fallback behaviour, etc.
"""

from typing import Any, Dict
from k9_aif_abb.k9_orchestrators.intent_orchestrator import IntentOrchestrator


class AcmeIntentOrchestrator(IntentOrchestrator):
    """
    Domain SBB that adds payload enrichment before classification
    and a branded clarification message.
    """

    layer = "AcmeIntentOrchestrator SBB"

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Pre-processing: normalise message casing, strip noise
        if "message" in payload:
            payload = {**payload, "message": payload["message"].strip().lower()}

        result = super().execute_flow(payload)

        # Post-processing: audit every routing decision
        self.logger.info(
            "[%s] audit: event_type=%r → status=%s intent=%s",
            self.layer,
            payload.get("event_type"),
            result.get("status"),
            result.get("intent"),
        )
        return result

    def _clarification_message(self, intent: str, confidence: float, payload: Dict[str, Any]) -> str:
        return (
            "Welcome to Acme Insurance. I wasn't able to understand your request. "
            "Please choose from: Report a Claim, Report Fraud, or Upload a Document."
        )
