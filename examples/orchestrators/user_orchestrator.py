# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ACME HealthCare UserOrchestrator (SBB)
# Routes sign-in and registration actions to the AuthAgent.

from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_projects.acme_health_insurance.agents.auth_agent import AuthAgent


class UserOrchestrator(BaseOrchestrator):
    """
    UserOrchestrator
    ================
    Orchestrator managing authentication-related tasks.
    Coordinates user sign-in and registration flows using AuthAgent.
    """

    layer = "User Orchestrator SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config=config or {}, monitor=monitor, **kwargs)
        self.auth_agent = AuthAgent(config=self.config, monitor=self.monitor)
        self.logger.info(f"[{self.layer}] Initialized UserOrchestrator")

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the user authentication workflow."""
        self.logger.info(f"[{self.layer}] ▶ Starting auth orchestration with payload={payload}")
        try:
            result = self.auth_agent.execute(payload)
            reply = result.get("reply", "No response from AuthAgent.")
            self.publish_status("completed", {"user": payload.get("username"), "action": payload.get("action")})
            return {"reply": reply, "status": result.get("status", "unknown")}
        except Exception as e:
            self.logger.error(f"[{self.layer}] ❌ Auth flow error: {e}")
            self.publish_status("error", {"error": str(e)})
            return {"reply": f"Authentication failed: {e}"}