# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_orchestrators/liveagent_orchestrator.py

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class LiveAgentOrchestrator(BaseAgent):
    """
    K9-AIF LiveAgentOrchestrator ABB
    --------------------------------
    Routes user interactions to a human support channel
    (e.g., Slack, Teams, ServiceNow, or call center bridge).
    """

    layer = "LiveAgent Orchestrator ABB"

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.log(" LiveAgentOrchestrator execution started")

        try:
            query = payload.get("message", "")
            reply = (
                " **LiveAgentOrchestrator**\n"
                f"Your query has been forwarded to a human support specialist.\n\n"
                f"**Summary:** {query}\n"
                f"A Live Agent will follow up shortly."
            )

            if getattr(self, "messaging", None):
                self.messaging.publish({
                    "event_type": "escalation_triggered",
                    "layer": self.layer,
                    "status": "initiated",
                })

            self.log("[OK] LiveAgent escalation initiated")
            return {"reply": reply}

        except Exception as e:
            self.log(f"[ERROR] LiveAgent orchestration error: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": "[WARN] Live agent escalation failed."}