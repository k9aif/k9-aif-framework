# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  MonitorAgent (Acme Health Insurance)

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_projects.acme_health_insurance.agents.persistence_agent import PersistenceAgent


class MonitorAgent(BaseAgent):
    """Monitors and logs orchestration events for audit and traceability."""

    layer = "Monitor SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized MonitorAgent with Persistence bridge")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "event": "Eligibility verified",
            "agent": "EligibilityAgent"
        }
        """
        try:
            record = {
                "event": payload.get("event"),
                "agent": payload.get("agent", "unknown"),
                "logged_at": datetime.now().isoformat(),
            }

            result = self.persistence.execute({
                "action": "insert",
                "table": "event_log",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Logged event from {record['agent']}.", "INFO")
                return {"status": "success", "event": record["event"]}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Monitor log failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}