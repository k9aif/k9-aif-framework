# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_escalation_agent (SBB)
#
# Responsibilities:
#   - Evaluate agent confidence against configured threshold
#   - Package escalation context (event, agent reasoning, decision record)
#   - Submit escalation ticket to the HITL queue (escalation_tickets table)
#   - Emit escalation event on the event bus

import uuid
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_insert_ignore


DEFAULT_CONFIDENCE_THRESHOLD = 0.75
DEFAULT_RISK_THRESHOLD = 0.8


class EscalationAgent(BaseAgent):
    """
    SBB: k9_sbb_escalation_agent

    Confidence-threshold-based HITL escalation packaging.
    Does not invoke an LLM — purely deterministic routing logic.
    """

    layer = "EOC Escalation SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        eoc_cfg = self.config.get("eoc", {})
        self._threshold = float(eoc_cfg.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))
        # Matches RiskAssessmentSquad's own stated escalation_risk_threshold
        # (squads.yaml config: blocks are descriptive only, never read by
        # SquadLoader — this is the actual enforcement point).
        self._risk_threshold = float(eoc_cfg.get("escalation_risk_threshold", DEFAULT_RISK_THRESHOLD))
        self.logger.info(
            f"[{self.layer}] confidence_threshold={self._threshold} risk_threshold={self._risk_threshold}"
        )

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_id = payload.get("event_id") or str(uuid.uuid4())

        # read confidence from flat payload or from accumulated adjudication/intent/
        # fraud_assessment result (FraudDetectionAgent sets confidence == risk_score —
        # "risk score is the confidence signal for fraud", see fraud_detection_agent.py).
        # Falling back to 1.0 when none apply previously made every fraud-only
        # escalation ticket show a misleadingly "fully confident" 1.0.
        fraud = payload.get("fraud_assessment") or {}
        adj = payload.get("adjudication") or payload.get("intent") or fraud or {}
        confidence = float(
            payload["confidence"] if "confidence" in payload
            else adj.get("confidence", 1.0)
        )

        # read guard result from accumulated guard context or flat guard_passed key
        guard_result = payload.get("guard", {})
        if "guard_passed" in payload:
            guard_failed = not bool(payload["guard_passed"])
        else:
            guard_failed = not bool(guard_result.get("passed", True))

        force_escalate = payload.get("force_escalate", False)

        # risk_score comes from FraudDetectionAgent's result_key ("fraud_assessment")
        # in RiskAssessmentSquad, but read a flat fallback too so any other squad
        # that surfaces a top-level risk_score is covered without a code change.
        risk_score_raw = fraud.get("risk_score", payload.get("risk_score"))
        risk_score = float(risk_score_raw) if risk_score_raw is not None else None
        high_risk = risk_score is not None and risk_score >= self._risk_threshold

        should_escalate = (
            force_escalate
            or confidence < self._threshold
            or guard_failed
            or high_risk
        )

        ticket_id = None
        escalation_reason = self._build_reason(
            confidence, guard_failed, force_escalate, risk_score, high_risk, fraud
        )

        if should_escalate:
            ticket_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
            ticket = {
                "ticket_id": ticket_id,
                "event_id": event_id,
                "event_type": payload.get("event_type", "unknown"),
                "squad_id": payload.get("squad_id", "unknown"),
                "agent_name": payload.get("source_agent") or self._infer_source_agent(payload),
                "reason": escalation_reason,
                "confidence_score": confidence,
                "context_payload": json.dumps(self._safe_context(payload, fraud)),
                "agent_rationale": payload.get("rationale") or fraud.get("rationale", ""),
                "priority": self._derive_priority(confidence, guard_failed, risk_score),
                "status": "open",
                "correlation_id": correlation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            self._persist(ticket)

            self.publish_event({
                "type": "EscalationRaised",
                "ticket_id": ticket_id,
                "correlation_id": correlation_id,
                "reason": escalation_reason,
                "priority": ticket["priority"],
            })

            self.logger.warning(
                f"[{self.layer}] ESCALATION raised: ticket={ticket_id} "
                f"confidence={confidence:.2f} guard_failed={guard_failed} "
                f"risk_score={risk_score} priority={ticket['priority']}"
            )
        else:
            ticket = {}
            self.logger.info(
                f"[{self.layer}] No escalation needed: confidence={confidence:.2f} >= {self._threshold}, "
                f"risk_score={risk_score}"
            )

        return {
            "agent": "EscalationAgent",
            "event_id": event_id,
            "correlation_id": correlation_id,
            "should_escalate": should_escalate,
            "ticket_id": ticket_id,
            "escalation_reason": escalation_reason if should_escalate else None,
            "ticket": ticket,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    def _persist(self, ticket: Dict[str, Any]) -> None:
        try:
            with pg_connect(self.config) as conn:
                pg_insert_ignore(conn, "eoc.escalation_tickets", {
                    "ticket_id":       ticket["ticket_id"],
                    "event_id":        ticket.get("event_id"),
                    "event_type":      ticket.get("event_type"),
                    "squad_id":        ticket.get("squad_id"),
                    "agent_name":      ticket.get("agent_name"),
                    "reason":          ticket.get("reason", ""),
                    "confidence_score": ticket.get("confidence_score"),
                    "context_payload": json.dumps(json.loads(ticket.get("context_payload", "{}"))),
                    "agent_rationale": ticket.get("agent_rationale", ""),
                    "priority":        ticket.get("priority", "normal"),
                    "status":          "open",
                    "correlation_id":  ticket.get("correlation_id"),
                }, "ticket_id")
                conn.commit()
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] PG persist failed: {exc}")

    def _build_reason(
        self, confidence: float, guard_failed: bool, forced: bool,
        risk_score: Optional[float], high_risk: bool,
        fraud: Optional[Dict[str, Any]] = None,
    ) -> str:
        reasons = []
        if forced:
            reasons.append("forced escalation requested")
        if confidence < self._threshold:
            reasons.append(f"confidence {confidence:.2f} below threshold {self._threshold}")
        if guard_failed:
            reasons.append("guard check failed (PII or policy violation)")
        if high_risk:
            signals = (fraud or {}).get("signals") or []
            signal_str = f" [{', '.join(signals[:3])}]" if signals else ""
            reasons.append(
                f"risk score {risk_score:.2f} at/above threshold {self._risk_threshold}{signal_str}"
            )
        return "; ".join(reasons) if reasons else "unknown"

    def _derive_priority(self, confidence: float, guard_failed: bool, risk_score: Optional[float] = None) -> str:
        if guard_failed or confidence < 0.3 or (risk_score is not None and risk_score >= 0.9):
            return "critical"
        if confidence < 0.5 or (risk_score is not None and risk_score >= self._risk_threshold):
            return "high"
        if confidence < self._threshold:
            return "normal"
        return "low"

    def _infer_source_agent(self, payload: Dict[str, Any]) -> str:
        """Best-effort attribution when the flow didn't set source_agent explicitly."""
        if "fraud_assessment" in payload:
            return "FraudDetectionAgent"
        if "adjudication" in payload:
            return "AdjudicationAgent"
        if "intent" in payload:
            return "ClaimsTriageAgent"
        return "unknown"

    def _safe_context(self, payload: Dict[str, Any], fraud: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Flat event fields — includes both amount spellings scenarios use
        # (amount / amount_claimed) plus the fields that actually explain a
        # fraud alert (severity, alert_source, description). Without these a
        # ticket only ever showed "risk score 0.98" with no supporting
        # narrative for a human reviewer to act on.
        safe_keys = [
            "claim_id", "claimant_id", "policy_id", "event_id", "event_type",
            "squad_id", "priority", "claim_type", "amount", "amount_claimed",
            "severity", "alert_source", "description",
            "decision", "confidence", "completeness_score", "coverage_match",
            "correlation_id",
        ]
        ctx = {k: payload[k] for k in safe_keys if k in payload}

        fraud = fraud if fraud is not None else (payload.get("fraud_assessment") or {})
        if fraud:
            ctx["risk_score"] = fraud.get("risk_score")
            ctx["fraud_signals"] = fraud.get("signals")
            ctx["fraud_recommendation"] = fraud.get("recommendation")
            ctx["fraud_rationale"] = fraud.get("rationale")
        return ctx
