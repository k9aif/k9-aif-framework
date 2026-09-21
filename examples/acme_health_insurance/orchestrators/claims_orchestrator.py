# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# ACME HealthCare  ClaimsOrchestrator (SBB)
# Coordinates claim filing, inquiry, and appeal flows with router-based reasoning.

import traceback
from typing import Dict, Any

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
from ..agents.claim_processing_agent import ClaimProcessingAgent


class ClaimsOrchestrator(BaseOrchestrator):
    """
    Specialized orchestrator for ACME HealthCare claims operations.
    """

    layer = "Claims Orchestrator SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config=config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initialized ClaimsOrchestrator")

        self.claim_agent = ClaimProcessingAgent(config=self.config, monitor=monitor)

    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.publish_status("started", {"event": "claims_flow_started"})
        self.logger.info(f"[{self.layer}] Execution started")

        try:
            query = payload.get("message", "").strip()
            if not query:
                return {"reply": " Please describe your claim question or issue."}

            intent = "general_inquiry"

            try:
                intent_prompt = (
                    "Classify the user's claim request.\n\n"
                    f"Text: '{query}'\n\n"
                    "Possible intents: [submit_claim, check_status, appeal_claim, general_inquiry]. "
                    "Respond with one intent only."
                )

                req = InferenceRequest(
                    prompt=intent_prompt,
                    task_type="chat",
                    metadata={
                        "agent": "claims_orchestrator",
                        "stage": "intent_classification",
                    },
                )

                response = llm_invoke(self.config, req)
                intent = (response.output or "").strip().lower()

                self.logger.info(
                    f"[{self.layer}] Detected claim intent: {intent} "
                    f"(model={response.model_alias}, provider={response.provider})"
                )
            except Exception as le:
                self.logger.warning(f"[{self.layer}] Router classification failed: {le}")

            if "submit" in intent or "file" in query.lower():
                result = await self.claim_agent.execute(
                    {
                        "provider": "CityCare Hospital",
                        "member_id": "M12345",
                        "amount": 1250.50,
                        "status": "submitted",
                        "notes": query,
                    }
                )
                reply = (
                    f"Claim filed successfully!\n"
                    f"Claim ID: **{result.get('claim_id')}**\n"
                    f"Reasoning Summary:\n{result.get('summary', 'N/A')}"
                )

            elif "status" in intent or "check" in query.lower():
                reply = (
                    "**Claim Status Inquiry**\n"
                    "This feature will soon connect to ACME's backend Appian workflow.\n"
                    "For now, please provide a claim ID to simulate status lookup."
                )

            elif "appeal" in intent or "dispute" in query.lower():
                reply = (
                    "**Claim Appeal Request**\n"
                    "Thank you. Your appeal is being reviewed by ACME Health Appeals team.\n"
                    "You'll receive an update via email within 2 business days."
                )

            else:
                reply = (
                    "**Claims Support System**\n"
                    f"Received your request: **{query}**\n"
                    "ACME's claims verification and escalation workflow is under setup.\n"
                    "Please check back soon for integrated claim tracking."
                )

            self.publish_status("completed", {"intent": intent, "reply": reply})
            self.logger.info(f"[{self.layer}] Execution complete")
            return {"reply": reply}

        except Exception as e:
            self.publish_status("error", {"error": str(e)})
            self.logger.error(f"[{self.layer}] Error: {e}")
            traceback.print_exc()
            return {"reply": f"An internal error occurred in claims orchestration: {str(e)}"}