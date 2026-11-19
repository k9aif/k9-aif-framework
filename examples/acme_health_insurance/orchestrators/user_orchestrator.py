# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  ACME HealthCare UserOrchestrator (SBB)
# Runs AuthSquad (config/squads.yaml) for sign-in and registration.

from typing import Dict, Any
from .acme_squads import AcmeDomainOrchestrator


class UserOrchestrator(AcmeDomainOrchestrator):
    """
    UserOrchestrator
    ================
    Orchestrator managing authentication-related tasks.
    Runs AuthSquad (config/squads.yaml) for sign-in and registration.
    """

    layer = "User Orchestrator SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config=config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initialized UserOrchestrator")

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the user authentication workflow."""
        # Screen ingress with this orchestrator's governance (Shield from config.yaml).
        try:
            payload = await self.apply_pre_governance(payload)
        except PermissionError as exc:
            self.logger.warning(f"[{self.layer}] request blocked by governance: {exc}")
            return {"reply": "Request blocked by governance.", "status": "denied", "reason": str(exc)}
        self.logger.info(f"[{self.layer}]  Starting auth orchestration with payload={payload}")
        try:
            result = (await self.run_squad("AuthSquad", payload))["auth"]
            reply = result.get("reply", "No response from the sign-in service.")
            self.publish_status("completed", {"user": payload.get("username"), "action": payload.get("action")})
            return {"reply": reply, "status": result.get("status", "unknown")}
        except Exception as e:
            self.logger.error(f"[{self.layer}]  Auth flow error: {e}")
            self.publish_status("error", {"error": str(e)})
            return {"reply": f"Authentication failed: {e}", "status": "error"}