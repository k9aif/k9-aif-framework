# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  ClaimProcessingAgent (Acme Health Insurance)
# Extends claim persistence with router-based reasoning and compliance checks.

from datetime import datetime
from typing import Dict, Any

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter
from .persistence_agent import PersistenceAgent


class ClaimProcessingAgent(BaseAgent):
    """SBB Agent for processing, reasoning, and persisting health insurance claims."""

    layer = "ClaimProcessing SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.persistence = PersistenceAgent(config=self.config)
        self.logger.info(f"[{self.layer}] Initialized ClaimProcessingAgent with Persistence bridge")

        try:
            self.catalog = ModelCatalog(self.config)
            self.router = K9ModelRouter(self.catalog)
            self.logger.info(f"[{self.layer}] K9ModelRouter initialized successfully")
        except Exception as e:
            self.logger.error(f"[{self.layer}] Router initialization failed: {e}")
            self.catalog = None
            self.router = None

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

            reasoning_summary = ""
            compliance_flag = "clear"

            if self.router:
                try:
                    prompt = (
                        f"Analyze this insurance claim:\n"
                        f"Provider: {record['provider']}\n"
                        f"Amount: {record['amount']}\n"
                        f"Status: {record['status']}\n"
                        f"Notes: {record['notes']}\n\n"
                        f"Return a concise summary and detect if the claim seems unusually high or potentially fraudulent."
                    )

                    req = InferenceRequest(
                        prompt=prompt,
                        task_type="reasoning",
                        metadata={"agent": "claim_processing_agent", "stage": "reasoning"},
                    )

                    response = await self.router.ainvoke(req)
                    reasoning_summary = (response.output or "").strip()
                    self.logger.info(
                        f"[{self.layer}] Claim reasoning complete "
                        f"(model={response.model_alias}, provider={response.provider})."
                    )
                except Exception as le:
                    self.logger.warning(f"[{self.layer}] Router reasoning skipped: {le}")

            if self.router:
                try:
                    guard_prompt = (
                        f"Check if this claim text contains sensitive or prohibited data:\n"
                        f"{record['notes']}"
                    )

                    guard_req = InferenceRequest(
                        prompt=guard_prompt,
                        task_type="policy",
                        sensitivity="confidential",
                        metadata={"agent": "claim_processing_agent", "stage": "compliance"},
                    )

                    guard_resp = await self.router.ainvoke(guard_req)
                    guard_text = (guard_resp.output or "").strip()

                    if "prohibited" in guard_text.lower() or "violation" in guard_text.lower():
                        compliance_flag = "flagged"

                    self.logger.info(
                        f"[{self.layer}] Compliance check result: {compliance_flag} "
                        f"(model={guard_resp.model_alias}, provider={guard_resp.provider})."
                    )
                except Exception as ge:
                    self.logger.warning(f"[{self.layer}] Router compliance check skipped: {ge}")

            result = self.persistence.execute({
                "action": "insert",
                "table": "claims",
                "data": record,
            })

            if result.get("status") == "success":
                self.logger.info(f"[{self.layer}] Claim {claim_id} persisted successfully.")
                return {
                    "status": "success",
                    "claim_id": claim_id,
                    "row_id": result.get("row_id"),
                    "summary": reasoning_summary,
                    "compliance": compliance_flag,
                }

            raise RuntimeError(result.get("error", "Insert failed"))

        except Exception as e:
            self.logger.error(f"[{self.layer}] Claim processing failed: {e}")
            return {"status": "error", "error": str(e)}