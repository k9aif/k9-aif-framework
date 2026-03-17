# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  FallbackOrchestrator (ABB)
# Provides safe default responses for unknown intents or routing failures.

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator


class FallbackOrchestrator(BaseOrchestrator):
    """
    FallbackOrchestrator
    ====================
    Default safety-net orchestrator for unrecognized intents or routing errors.

    Responsibilities
    ----------------
     Handles unknown or unmapped intents gracefully.  
     Provides standardized, governed fallback messages.  
     Publishes orchestration events to the monitoring and governance layer.  
     Ensures that the user experience never results in a dead end.

    Attributes
    ----------
    layer : str
        Logical name for orchestration and monitoring ("Fallback Orchestrator ABB").
    """

    layer = "Fallback Orchestrator ABB"

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the fallback orchestration flow.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input message or contextual data that failed routing.

        Returns
        -------
        Dict[str, Any]
            Standardized reply payload with fallback guidance.
        """
        self.logger.info(f"[{self.layer}]  Execution started with payload={payload}")
        self.publish_status("started", {"event": "fallback_invoked"})

        try:
            query = payload.get("message", "")
            intent = payload.get("intent", "unknown")

            # ------------------------------------------------------------------
            # Step 1  Generate fallback message
            # ------------------------------------------------------------------
            reply = (
                "**Im not sure I understood that fully.**\n\n"
                "Your question didnt match any known topics or orchestrators.\n"
                "Heres what you can do:\n"
                "- Ask about your health plan or coverage\n"
                "- Find a doctor or provider\n"
                "- Get help with claims or billing\n"
                "- Talk to a live ACME HealthCare agent\n\n"
                "If you meant something else, please rephrase your request."
            )

            # ------------------------------------------------------------------
            # Step 2  Publish fallback event to governance channel
            # ------------------------------------------------------------------
            self.publish_status("fallback_triggered", {
                "intent": intent,
                "query": query,
                "layer": self.layer
            })

            self.logger.info(f"[{self.layer}]  Fallback engaged for intent={intent}")
            return {"reply": reply}

        except Exception as e:
            self.logger.error(f"[{self.layer}]  Error during fallback: {e}")
            self.publish_status("error", {"error": str(e)})
            traceback.print_exc()
            return {"reply": "An internal fallback error occurred."}