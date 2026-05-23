# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_claims_triage_agent (SBB)
#
# Responsibilities:
#   - Completeness check: verifies all required claim fields are present
#   - Coverage match: checks claim type against active policy coverage
#   - Priority scoring: assigns priority (critical/high/normal/low) based on amount and type
#   - Emits triage result for downstream AdjudicationAgent

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_upsert, pg_insert_ignore


REQUIRED_CLAIM_FIELDS = ["claim_id", "claimant_id", "policy_id", "claim_type", "amount_claimed"]

PRIORITY_THRESHOLDS = {
    "critical": 100_000,
    "high": 25_000,
    "normal": 5_000,
}


class ClaimsTriageAgent(BaseAgent):
    """
    SBB: k9_sbb_claims_triage_agent

    Triages incoming claims: completeness check, coverage match, priority scoring.
    Uses K9ModelRouter (via EOCModelRouter) for LLM-assisted triage reasoning.
    """

    layer = "EOC ClaimsTriage SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_id = payload.get("event_id") or str(uuid.uuid4())

        missing = [f for f in REQUIRED_CLAIM_FIELDS if not payload.get(f)]
        completeness_score = round(1.0 - len(missing) / len(REQUIRED_CLAIM_FIELDS), 2)

        amount = float(payload.get("amount_claimed", 0))
        priority = self._score_priority(amount)
        coverage_match = self._check_coverage(payload)

        reasoning = ""
        if completeness_score == 1.0:
            prompt = (
                f"Insurance claim triage:\n"
                f"Claim type: {payload.get('claim_type')}\n"
                f"Amount: ${amount:,.2f}\n"
                f"Policy ID: {payload.get('policy_id')}\n"
                f"Notes: {payload.get('notes', 'none')}\n\n"
                f"Provide a brief triage assessment (2-3 sentences). "
                f"Flag any concerns about completeness, coverage, or unusual amounts."
            )
            req = InferenceRequest(
                prompt=prompt,
                task_type="reasoning",
                metadata={"agent": "ClaimsTriageAgent", "correlation_id": correlation_id},
            )
            resp = llm_invoke(self.config, req)
            reasoning = resp.output.strip()

        result = {
            "agent": "ClaimsTriageAgent",
            "event_id": event_id,
            "correlation_id": correlation_id,
            "claim_id": payload.get("claim_id"),
            "completeness_score": completeness_score,
            "missing_fields": missing,
            "coverage_match": coverage_match,
            "priority": priority,
            "amount_claimed": amount,
            "triage_reasoning": reasoning,
            "confidence": completeness_score * (0.9 if coverage_match else 0.5),
            "is_resubmission": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        is_resubmission = self._persist(payload, result)
        result["is_resubmission"] = is_resubmission
        if is_resubmission:
            result["priority"] = "critical"
            self.logger.warning(
                f"[{self.layer}] Resubmission detected: claim={payload.get('claim_id')} — forcing priority=critical"
            )

        self.publish_event({
            "type": "ClaimsTriageCompleted",
            "agent": "ClaimsTriageAgent",
            "correlation_id": correlation_id,
            "priority": priority,
            "completeness_score": completeness_score,
        })

        self.logger.info(
            f"[{self.layer}] Triage complete: claim={payload.get('claim_id')} "
            f"priority={priority} completeness={completeness_score} coverage={coverage_match}"
        )
        return result

    # ------------------------------------------------------------------
    def _score_priority(self, amount: float) -> str:
        if amount >= PRIORITY_THRESHOLDS["critical"]:
            return "critical"
        if amount >= PRIORITY_THRESHOLDS["high"]:
            return "high"
        if amount >= PRIORITY_THRESHOLDS["normal"]:
            return "normal"
        return "low"

    def _persist(self, payload: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """Persist claim data. Returns True if this claim_id already existed (resubmission)."""
        is_resubmission = False
        try:
            with pg_connect(self.config) as conn:
                # Detect resubmission before overwriting
                claim_id = payload.get("claim_id")
                if claim_id:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM eoc.claims WHERE claim_id = %s", (claim_id,))
                        is_resubmission = cur.fetchone() is not None

                # Upsert claimant (name unknown from payload — store ID only)
                if payload.get("claimant_id"):
                    pg_upsert(conn, "eoc.claimants", {
                        "claimant_id": payload["claimant_id"],
                        "name": payload.get("claimant_name", payload["claimant_id"]),
                        "email": payload.get("email"),
                        "phone": payload.get("phone"),
                    }, "claimant_id")

                # Upsert policy stub so the FK from claims is satisfied
                if payload.get("policy_id"):
                    pg_upsert(conn, "eoc.policies", {
                        "policy_id":   payload["policy_id"],
                        "claimant_id": payload.get("claimant_id"),
                        "policy_type": payload.get("claim_type", "unknown"),
                        "status":      "active",
                    }, "policy_id")

                # Upsert claim
                if claim_id:
                    pg_upsert(conn, "eoc.claims", {
                        "claim_id":          claim_id,
                        "claimant_id":       payload.get("claimant_id"),
                        "policy_id":         payload.get("policy_id"),
                        "event_id":          payload.get("event_id"),
                        "claim_type":        payload.get("claim_type"),
                        "amount_claimed":    payload.get("amount_claimed", 0),
                        "priority":          result.get("priority", "normal"),
                        "status":            "resubmitted" if is_resubmission else payload.get("status", "submitted"),
                        "completeness_score": result.get("completeness_score"),
                        "coverage_match":    result.get("coverage_match"),
                        "notes":             payload.get("notes"),
                        "correlation_id":    result.get("correlation_id"),
                    }, "claim_id")

                conn.commit()
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] PG persist failed: {exc}")
        return is_resubmission

    def _check_coverage(self, payload: Dict[str, Any]) -> bool:
        # Stub: in production this queries the policies table.
        # Returns True if claim_type is plausible given policy context.
        claim_type = (payload.get("claim_type") or "").lower()
        return claim_type not in ("", "unknown")
