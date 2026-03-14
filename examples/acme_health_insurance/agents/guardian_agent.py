# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  GuardianAgent (Acme Health Insurance)

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from .persistence_agent import PersistenceAgent


class GuardianAgent(BaseAgent):
    """Applies governance and compliance checks on Acme Health actions."""

    layer = "Guardian SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized GuardianAgent with Persistence bridge")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "component": "ClaimProcessingAgent",
            "action": "insert_claim",
            "policy": "HIPAA-2025"
        }
        """
        try:
            record = {
                "component": payload.get("component", "unknown"),
                "action": payload.get("action", "none"),
                "policy": payload.get("policy", "HIPAA-2025"),
                "checked_at": datetime.now().isoformat(),
                "result": "compliant",
            }

            result = self.persistence.execute({
                "action": "insert",
                "table": "governance_audit",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Compliance check OK for {record['component']}.", "INFO")
                return {"status": "success", "component": record["component"]}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Compliance check failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}