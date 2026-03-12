# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ACME HealthCare AuthAgent (SBB)
# Handles mock sign-in and registration workflows.

from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class AuthAgent(BaseAgent):
    """
    AuthAgent
    =========
    Agent responsible for basic authentication tasks such as:
    • Sign-in verification
    • Member/Provider/Employer registration

    Notes
    -----
    - Currently operates in mock mode (Phase 1).
    - In future, integrate with PersistenceAgent for DB or API validation.
    """

    layer = "Auth Agent SBB"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes authentication flow (mock mode)."""
        self.logger.info(f"[{self.layer}] ▶ Executing AuthAgent with payload={payload}")

        action = payload.get("action")
        username = payload.get("username", "").strip()

        if not action or not username:
            return {"reply": "⚠️ Missing required fields (action or username)."}

        # Mocked sign-in / registration behavior
        if action == "signin":
            reply = f"✅ Welcome back, {username}! (mock login)"
            status = "signed_in"
        elif action == "register":
            reply = f"📝 User '{username}' successfully registered (mock)."
            status = "registered"
        else:
            reply = f"❓ Unknown auth action '{action}'"
            status = "unknown"

        # Publish governance event
        self.publish_event({
            "event_type": "auth_event",
            "layer": self.layer,
            "user": username,
            "status": status
        })

        return {"reply": reply, "status": status}