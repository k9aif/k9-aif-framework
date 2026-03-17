# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  EligibilityAgent (Acme Health Insurance)

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from .persistence_agent import PersistenceAgent


class EligibilityAgent(BaseAgent):
    """SBB Agent for validating and persisting member eligibility checks."""

    layer = "Eligibility SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized EligibilityAgent with Persistence bridge")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "member_id": "M12345",
            "plan": "Acme Gold Plan",
            "verified_by": "system"
        }
        """
        try:
            record = {
                "member_id": payload.get("member_id"),
                "plan": payload.get("plan", "unknown"),
                "verified_by": payload.get("verified_by", "system"),
                "verified_at": datetime.now().isoformat(),
                "status": "eligible"
            }

            result = self.persistence.execute({
                "action": "insert",
                "table": "eligibility_checks",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Eligibility for member {record['member_id']} verified.", "INFO")
                return {"status": "success", "member_id": record["member_id"]}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Eligibility check failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}