# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  MemberLoginAgent (Acme Health Insurance)
# Handles member login validation using email lookup.

from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_projects.acme_health_insurance.agents.persistence_agent import PersistenceAgent


class MemberLoginAgent(BaseAgent):
    """SBB Agent for validating member login credentials."""

    layer = "MemberLogin SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized with Persistence bridge")

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "email": "john.doe@example.com"
        }
        """
        try:
            email = payload.get("email")
            if not email:
                return {"status": "error", "error": "Email is required."}

            result = self.persistence.execute({
                "action": "select",
                "table": "members",
                "where": {"email": email}
            })

            rows = result.get("rows", [])
            if not rows:
                self.log(f"[{self.layer}] Login failed: email not found", "WARN")
                return {"status": "error", "error": "Member not found."}

            member = rows[0]
            self.log(f"[{self.layer}] Login success for {email}", "INFO")
            return {
                "status": "success",
                "member_id": member.get("member_id"),
                "first_name": member.get("first_name"),
                "plan": member.get("plan")
            }

        except Exception as e:
            self.log(f"[{self.layer}] Login failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}