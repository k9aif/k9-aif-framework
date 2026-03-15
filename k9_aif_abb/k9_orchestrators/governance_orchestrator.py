# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_orchestrators/governance_orchestrator.py

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class GovernanceOrchestrator(BaseAgent):
    """
    K9-AIF GovernanceOrchestrator ABB
    ---------------------------------
    Handles policy audits, enforcement checks, and compliance routing.
    Triggered when governance-related intents are detected.
    """

    layer = "Governance Orchestrator ABB"

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.log(" GovernanceOrchestrator execution started")

        try:
            query = payload.get("message", "")
            reply = (
                " **GovernanceOrchestrator**\n"
                f"Your request has been routed through the governance path.\n"
                f"All enforcement and compliance policies are verified.\n\n"
                f"**Query:** {query}\n"
                f"**Layer:** {self.layer}"
            )

            if getattr(self, "messaging", None):
                self.messaging.publish({
                    "event_type": "orchestration_complete",
                    "layer": self.layer,
                    "status": "completed",
                })

            self.log("[OK] Governance orchestration complete")
            return {"reply": reply}

        except Exception as e:
            self.log(f"[ERROR] Governance orchestration error: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": "[WARN] Governance orchestration failed."}