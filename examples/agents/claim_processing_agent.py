# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ClaimProcessingAgent (Acme Health Insurance)
# Extends claim persistence with LLM-based reasoning and compliance checks.

from datetime import datetime
from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_projects.acme_health_insurance.agents.persistence_agent import PersistenceAgent
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


class ClaimProcessingAgent(BaseAgent):
    """SBB Agent for processing, reasoning, and persisting health insurance claims."""

    layer = "ClaimProcessing SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized ClaimProcessingAgent with Persistence bridge")

        # 🧠 Load LLM instances
        try:
            self.llm_general = LLMFactory.get("general")
            self.llm_guardian = LLMFactory.get("guardian")
            self.logger.info(f"[{self.layer}] ✅ LLMs initialized (general + guardian)")
        except Exception as e:
            self.logger.error(f"[{self.layer}] ⚠️ LLM initialization failed: {e}")
            self.llm_general = None
            self.llm_guardian = None

    # ------------------------------------------------------------------
    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected payload:
        {
            "claim_id": "C12345",
            "member_id": "M67890",
            "amount": 1250.50,
            "provider": "CityCare Hospital",
            "status": "submitted",
            "notes": "Member visited ER for minor injury"
        }
        """
        try:
            claim_id = payload.get("claim_id") or f"CLM-{datetime.now().strftime('%y%m%d%H%M%S')}"
            record = {
                "claim_id": claim_id,
                "member_id": payload.get("member_id"),
                "provider": payload.get("provider"),
                "amount": payload.get("amount", 0.0),
                "status": payload.get("status", "submitted"),
                "submitted_at": datetime.now().isoformat(),
                "notes": payload.get("notes", ""),
            }

            # 🧠 Optional: Run reasoning step if LLM available
            reasoning_summary = ""
            compliance_flag = "clear"

            if self.llm_general:
                try:
                    prompt = (
                        f"Analyze this insurance claim:\n"
                        f"Provider: {record['provider']}\n"
                        f"Amount: {record['amount']}\n"
                        f"Status: {record['status']}\n"
                        f"Notes: {record['notes']}\n\n"
                        f"Return a concise summary and detect if the claim seems unusually high or potentially fraudulent."
                    )
                    result = await self.llm_general.ainvoke(prompt)
                    reasoning_summary = result if isinstance(result, str) else str(result)
                    self.logger.info(f"[{self.layer}] 🧠 Claim reasoning complete.")
                except Exception as le:
                    self.logger.warning(f"[{self.layer}] ⚠️ LLM reasoning skipped: {le}")

            # 🛡️ Optional: Guardian compliance screening
            if self.llm_guardian:
                try:
                    guard_prompt = (
                        f"Check if this claim text contains sensitive or prohibited data:\n"
                        f"{record['notes']}"
                    )
                    guard_resp = await self.llm_guardian.ainvoke(guard_prompt)
                    if "prohibited" in guard_resp.lower() or "violation" in guard_resp.lower():
                        compliance_flag = "flagged"
                    self.logger.info(f"[{self.layer}] 🛡️ Compliance check result: {compliance_flag}")
                except Exception as ge:
                    self.logger.warning(f"[{self.layer}] ⚠️ Guardian check skipped: {ge}")

            # 💾 Persist claim
            result = self.persistence.execute({
                "action": "insert",
                "table": "claims",
                "data": record,
            })

            if result.get("status") == "success":
                self.log(f"[{self.layer}] Claim {claim_id} persisted successfully.", "INFO")
                return {
                    "status": "success",
                    "claim_id": claim_id,
                    "row_id": result.get("row_id"),
                    "summary": reasoning_summary,
                    "compliance": compliance_flag,
                }
            else:
                raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.log(f"[{self.layer}] ❌ Claim processing failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}