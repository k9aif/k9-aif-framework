# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_agents/chat/chat_agent_abb.py

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class ChatAgentABB(BaseAgent):
    """
    K9-AIF Chat Agent ABB - Governed Conversational Agent
    ----------------------------------------------------
    Provides the core orchestration and governance for all ChatAgents.
    Ensures:
      - Router enforcement via GovernanceFactory
      - Logging and audit events to MessageBus
      - Optional retrieval or LLM delegation handled by SBB subclass
    """

    layer = "Chat Agent ABB"

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes governed ABB-level chat flow."""
        self.log(" ChatAgentABB execution started")

        # ---------------- Governance Enforcement ----------------
        try:
            self.enforce_governance()
            self.log("[OK] Router enforcement passed")
        except PermissionError as e:
            self.log(str(e), level="ERROR")
            return {"reply": "[WARN] Governance enforcement failed - Router missing."}

        # ---------------- Input Validation ----------------
        if not payload or "message" not in payload:
            self.log("[WARN] Missing 'message' in payload", level="ERROR")
            return {"reply": "[WARN] No message provided."}

        query = payload["message"]

        # ---------------- Core Processing ----------------
        try:
            # ABB-level routing audit event
            if getattr(self, "messaging", None):
                event = {
                    "event_type": "chat_request_received",
                    "layer": self.layer,
                    "agent": self.__class__.__name__,
                    "query": query,
                    "status": "received",
                }
                try:
                    self.messaging.publish(event)
                except Exception:
                    pass

            # ABB baseline reply (SBB will override this)
            base_reply = (
                f"[{self.layer}] Your message has been received and is "
                f"routed through K9-AIF governance.\nMessage: {query}"
            )

            # ---------------- Publish Completion ----------------
            if getattr(self, "messaging", None):
                completion = {
                    "event_type": "chat_cycle_complete",
                    "layer": self.layer,
                    "agent": self.__class__.__name__,
                    "status": "completed",
                }
                try:
                    self.messaging.publish(completion)
                except Exception:
                    pass

            self.log("[OK] ChatAgentABB cycle completed")
            return {"reply": base_reply}

        except Exception as e:
            self.log(f"[ERROR] ChatAgentABB runtime error: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": "[WARN] Internal chat processing error."}