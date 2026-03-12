# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  PolicyAdvisorAgent (Acme Health Insurance)

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_projects.acme_health_insurance.agents.persistence_agent import PersistenceAgent


class PolicyAdvisorAgent(BaseAgent):
    """Provides benefit or coverage explanations and persists the query."""

    layer = "PolicyAdvisor SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized PolicyAdvisorAgent with Persistence bridge")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "question": "What does preventive care cover?",
            "member_id": "M12345"
        }
        """
        try:
            question = payload.get("question")
            # Simulated LLM response
            answer = "Preventive care includes annual checkups, screenings, and vaccines."

            record = {
                "member_id": payload.get("member_id"),
                "question": question,
                "answer": answer,
                "created_at": datetime.now().isoformat(),
            }

            result = self.persistence.execute({
                "action": "insert",
                "table": "policy_queries",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Advisory response saved for member {record['member_id']}.", "INFO")
                return {"status": "success", "answer": answer}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Policy advisory failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}