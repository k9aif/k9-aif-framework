# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  MemberRegistrationAgent (Acme Health Insurance)
# Handles registration of new members using governed persistence.

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from .persistence_agent import PersistenceAgent


class MemberRegistrationAgent(BaseAgent):
    """SBB Agent responsible for registering new members into the system."""

    layer = "MemberRegistration SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized with Persistence bridge")

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "first_name": "John",
            "last_name": "Doe",
            "dob": "1990-01-01",
            "plan": "SilverCare",
            "city": "Boston",
            "state": "MA",
            "zip_code": "02115",
            "phone": "555-111-2222",
            "email": "john.doe@example.com"
        }
        """
        try:
            # Basic validation
            if not payload.get("email"):
                return {"status": "error", "error": "Email is required."}

            member_id = f"MBR-{datetime.now().strftime('%y%m%d%H%M%S')}"
            record = {
                "member_id": member_id,
                "first_name": payload.get("first_name", "").strip(),
                "last_name": payload.get("last_name", "").strip(),
                "dob": payload.get("dob"),
                "plan": payload.get("plan", "BronzeCare"),
                "city": payload.get("city"),
                "state": payload.get("state"),
                "zip_code": payload.get("zip_code"),
                "phone": payload.get("phone"),
                "email": payload.get("email"),
                "created_at": datetime.now().isoformat(),
            }

            # Persist to database
            result = self.persistence.execute({
                "action": "insert",
                "table": "members",
                "data": record
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Registered member {member_id}", "INFO")
                return {"status": "success", "member_id": member_id}
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] Registration failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}