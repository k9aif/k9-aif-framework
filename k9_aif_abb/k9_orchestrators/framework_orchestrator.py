# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_orchestrators/framework_orchestrator.py

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class FrameworkOrchestrator(BaseAgent):
    """
    K9-AIF FrameworkOrchestrator ABB
    --------------------------------
    Default orchestrator for K9-AIF technical queries.
    Invoked by RouterAgent when intent = k9_technical.

    Responsibilities:
      - Validate orchestration flow
      - Log routing and orchestration lifecycle events
      - Delegate downstream to retriever or LLM as needed
    """

    layer = "Framework Orchestrator ABB"

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a governed orchestration flow."""
        self.log(" FrameworkOrchestrator execution started")

        try:
            query = payload.get("message", "")

            # Publish routing event
            if getattr(self, "messaging", None):
                event = {
                    "event_type": "orchestration_start",
                    "agent": self.__class__.__name__,
                    "layer": self.layer,
                    "query": query,
                    "status": "started",
                }
                try:
                    self.messaging.publish(event)
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Core orchestration logic (simple demo)
            # ------------------------------------------------------------------
            reply = (
                f"[INFO] K9-AIF FrameworkOrchestrator\n"
                f"Your question was routed successfully through the governed flow.\n\n"
                f"**Query:** {query}\n"
                f"**Handler:** {self.__class__.__name__}\n"
                f"**Layer:** {self.layer}\n"
            )

            # Publish orchestration completion event
            if getattr(self, "messaging", None):
                completion = {
                    "event_type": "orchestration_complete",
                    "agent": self.__class__.__name__,
                    "layer": self.layer,
                    "status": "completed",
                }
                try:
                    self.messaging.publish(completion)
                except Exception:
                    pass

            self.log("[OK] FrameworkOrchestrator execution complete")
            return {"reply": reply}

        except Exception as e:
            self.log(f"[ERROR] Orchestrator error: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": "[WARN] Framework orchestration failed."}