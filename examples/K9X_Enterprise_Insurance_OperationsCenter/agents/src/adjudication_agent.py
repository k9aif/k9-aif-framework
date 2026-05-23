# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_adjudication_agent (SBB)
#
# Responsibilities:
#   - Policy coverage reasoning via LLM
#   - Liability determination (approve / deny / partial / escalate)
#   - Recommendation generation with rationale
#   - Confidence scoring for downstream escalation gate

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_insert_ignore


class AdjudicationAgent(BaseAgent):
    """
    SBB: k9_sbb_adjudication_agent

    Policy coverage reasoning, liability determination, and recommendation generation.
    Routes to the reasoning-capable model (Granite 3.x) via EOCModelRouter.
    """

    layer = "EOC Adjudication SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_id = payload.get("event_id") or str(uuid.uuid4())

        triage = payload.get("triage", {})
        claim_id = payload.get("claim_id") or triage.get("claim_id")
        amount = float(payload.get("amount_claimed", triage.get("amount_claimed", 0)))
        claim_type = payload.get("claim_type", "")
        priority = triage.get("priority", "normal")
        is_resubmission = triage.get("is_resubmission", False)

        decision = "pending"
        rationale = ""
        confidence = 0.5
        recommendation = ""

        resubmit_note = "\n⚠ WARNING: This claim has been submitted before. Flag for duplicate review." if is_resubmission else ""
        prompt = (
            f"You are an insurance adjudication AI. Evaluate this claim:\n\n"
            f"Claim ID: {claim_id}\n"
            f"Claim Type: {claim_type}\n"
            f"Amount Claimed: ${amount:,.2f}\n"
            f"Priority: {priority}\n"
            f"Coverage Match: {triage.get('coverage_match', 'unknown')}\n"
            f"Notes: {payload.get('notes', 'none')}\n"
            f"Resubmission: {'YES — previously submitted' if is_resubmission else 'No'}"
            f"{resubmit_note}\n\n"
            f"Respond with:\n"
            f"DECISION: <approve|deny|partial|escalate>\n"
            f"CONFIDENCE: <0.0-1.0>\n"
            f"RATIONALE: <2-3 sentence explanation>\n"
            f"RECOMMENDATION: <actionable next step>"
        )
        req = InferenceRequest(
            prompt=prompt,
            task_type="adjudication",
            metadata={"agent": "AdjudicationAgent", "correlation_id": correlation_id},
        )
        resp = llm_invoke(self.config, req)
        raw = (resp.output or "").strip()

        decision, confidence, rationale, recommendation = self._parse_response(raw)
        self.logger.info(
            f"[{self.layer}] Adjudication: {decision} (confidence={confidence:.2f}) "
            f"model={resp.model_alias}"
        )

        prompt_hash = hashlib.sha256((claim_id or "").encode()).hexdigest()[:16]
        response_hash = hashlib.sha256(rationale.encode()).hexdigest()[:16]

        result = {
            "agent": "AdjudicationAgent",
            "event_id": event_id,
            "correlation_id": correlation_id,
            "claim_id": claim_id,
            "decision": decision,
            "confidence": confidence,
            "rationale": rationale,
            "recommendation": recommendation,
            "is_resubmission": is_resubmission,
            "prompt_hash": prompt_hash,
            "response_hash": response_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        self._persist(result)

        self.publish_event({
            "type": "AdjudicationCompleted",
            "agent": "AdjudicationAgent",
            "correlation_id": correlation_id,
            "decision": decision,
            "confidence": confidence,
        })

        return result

    # ------------------------------------------------------------------
    def _persist(self, result: Dict[str, Any]) -> None:
        if not result.get("claim_id"):
            return
        try:
            adjudication_id = f"ADJ-{uuid.uuid4().hex[:12].upper()}"
            with pg_connect(self.config) as conn:
                pg_insert_ignore(conn, "eoc.adjudication_records", {
                    "adjudication_id": adjudication_id,
                    "claim_id":        result.get("claim_id"),
                    "event_id":        result.get("event_id"),
                    "decision":        result.get("decision", ""),
                    "confidence_score": result.get("confidence", 0.0),
                    "rationale":       result.get("rationale", ""),
                    "prompt_hash":     result.get("prompt_hash"),
                    "response_hash":   result.get("response_hash"),
                    "disposition":     result.get("decision", ""),
                    "correlation_id":  result.get("correlation_id"),
                }, "adjudication_id")
                conn.commit()
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] PG persist failed: {exc}")

    def _parse_response(self, raw: str):
        decision = "escalate"
        confidence = 0.5
        rationale = raw
        recommendation = ""

        for line in raw.splitlines():
            line_lower = line.lower()
            if line_lower.startswith("decision:"):
                val = line.split(":", 1)[1].strip().lower()
                if val in ("approve", "deny", "partial", "escalate"):
                    decision = val
            elif line_lower.startswith("confidence:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    pass
            elif line_lower.startswith("rationale:"):
                rationale = line.split(":", 1)[1].strip()
            elif line_lower.startswith("recommendation:"):
                recommendation = line.split(":", 1)[1].strip()

        return decision, confidence, rationale, recommendation
