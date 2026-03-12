# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — NotificationAgent (Acme Health Insurance)

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_projects.acme_health_insurance.agents.persistence_agent import PersistenceAgent


class NotificationAgent(BaseAgent):
    """Sends user-facing notifications and persists audit trail."""

    layer = "Notification SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized NotificationAgent with Persistence bridge")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "recipient": "user@example.com",
            "event": "Claim submitted"
        }
        """
        try:
            record = {
                "recipient": payload.get("recipient"),
                "event": payload.get("event"),
                "sent_at": datetime.now().isoformat(),
                "status": "delivered"
            }

            result = self.persistence.execute({
                "action": "insert",
                "table": "notifications",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Notification sent to {record['recipient']}.", "INFO")
                return {"status": "success", "recipient": record["recipient"]}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Notification failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}