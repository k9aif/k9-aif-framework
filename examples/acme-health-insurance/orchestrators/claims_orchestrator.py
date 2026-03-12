# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# ACME HealthCare™ — ClaimsOrchestrator (SBB)
# Coordinates claim filing, inquiry, and appeal flows with LLM reasoning.

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_projects.acme_health_insurance.agents.claim_processing_agent import ClaimProcessingAgent


class ClaimsOrchestrator(BaseOrchestrator):
    """
    ClaimsOrchestrator
    ==================
    Specialized orchestrator for ACME HealthCare’s claims operations.

    Responsibilities
    ----------------
    • Classifies claim-related user intents using the LLMFactory.  
    • Coordinates claim creation, inquiry, and appeal flows.  
    • Delegates atomic tasks to subordinate agents (e.g., ClaimProcessingAgent).  
    • Publishes status updates through the monitoring and messaging layer.

    Notes
    -----
    - Inherits from :class:`BaseOrchestrator` to ensure consistency with
      K9-AIF orchestration semantics.
    - Supports asynchronous execution for integration with CrewAI event loops.

    Attributes
    ----------
    layer : str
        Logical layer name used for monitoring and logs.
    claim_agent : ClaimProcessingAgent
        Agent responsible for atomic claim processing actions.
    llm : Optional[Any]
        LLM interface instance from LLMFactory for reasoning and intent detection.
    """

    layer = "Claims Orchestrator SBB"

    # ------------------------------------------------------------------
    def __init__(self, config=None, monitor=None, **kwargs):
        """
        Initialize the ClaimsOrchestrator and its supporting agents.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration parameters for orchestration and agents.
        monitor : object, optional
            Monitoring instance implementing `record_event(event: Dict)`.
        """
        super().__init__(config=config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initialized ClaimsOrchestrator")

        # Load dependent agents
        self.claim_agent = ClaimProcessingAgent(config=self.config, monitor=monitor)

        # Initialize LLM for reasoning or fallback gracefully
        try:
            self.llm = LLMFactory.get("general")
            self.logger.info(f"[{self.layer}] ✅ LLM initialized for reasoning")
        except Exception as e:
            self.llm = None
            self.logger.warning(f"[{self.layer}] ⚠️ LLM unavailable: {e}")

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the asynchronous claim orchestration flow.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input message or structured request payload.

        Returns
        -------
        Dict[str, Any]
            Response dictionary containing user-facing reply text.
        """
        self.publish_status("started", {"event": "claims_flow_started"})
        self.logger.info(f"[{self.layer}] ▶ Execution started")

        try:
            query = payload.get("message", "").strip()
            if not query:
                return {"reply": "⚠️ Please describe your claim question or issue."}

            # Step 1️⃣ — Classify intent using LLM (if available)
            intent = "general_inquiry"
            if self.llm:
                try:
                    intent_prompt = (
                        "Classify the user's claim request.\n\n"
                        f"Text: '{query}'\n\n"
                        "Possible intents: [submit_claim, check_status, appeal_claim, general_inquiry]. "
                        "Respond with one intent only."
                    )
                    intent = await self.llm.ainvoke(intent_prompt)
                    intent = intent.strip().lower()
                    self.logger.info(f"[{self.layer}] 🧭 Detected claim intent: {intent}")
                except Exception as le:
                    self.logger.warning(f"[{self.layer}] ⚠️ LLM classification failed: {le}")

            # Step 2️⃣ — Handle intent branches
            if "submit" in intent or "file" in query.lower():
                result = await self.claim_agent.execute({
                    "provider": "CityCare Hospital",
                    "member_id": "M12345",
                    "amount": 1250.50,
                    "status": "submitted",
                    "notes": query
                })
                reply = (
                    f"Claim filed successfully!\n"
                    f"Claim ID: **{result.get('claim_id')}**\n"
                    f"Reasoning Summary:\n{result.get('summary', 'N/A')}"
                )

            elif "status" in intent or "check" in query.lower():
                reply = (
                    "**Claim Status Inquiry**\n"
                    "This feature will soon connect to ACME’s backend Appian workflow.\n"
                    "For now, please provide a claim ID to simulate status lookup."
                )

            elif "appeal" in intent or "dispute" in query.lower():
                reply = (
                    "⚖️ **Claim Appeal Request**\n"
                    "Thank you. Your appeal is being reviewed by ACME Health Appeals team.\n"
                    "You’ll receive an update via email within 2 business days."
                )

            else:
                reply = (
                    "**Claims Support System**\n"
                    f"Received your request: **{query}**\n"
                    "ACME’s claims verification and escalation workflow is under setup.\n"
                    "Please check back soon for integrated claim tracking."
                )

            self.publish_status("completed", {"intent": intent, "reply": reply})
            self.logger.info(f"[{self.layer}] ✅ Execution complete")
            return {"reply": reply}

        except Exception as e:
            self.publish_status("error", {"error": str(e)})
            self.logger.error(f"[{self.layer}] ❌ Error: {e}")
            traceback.print_exc()
            return {"reply": f"An internal error occurred in claims orchestration: {str(e)}"}