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
        self.logger.info(f"[{self.layer}] Threshold={self._threshold}")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_id = payload.get("event_id") or str(uuid.uuid4())

        # read confidence from flat payload or from accumulated adjudication/intent result
        adj = payload.get("adjudication") or payload.get("intent") or {}
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

        should_escalate = (
            force_escalate
            or confidence < self._threshold
            or guard_failed
        )

        ticket_id = None
        escalation_reason = self._build_reason(confidence, guard_failed, force_escalate)

        if should_escalate:
            ticket_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
            ticket = {
                "ticket_id": ticket_id,
                "event_id": event_id,
                "event_type": payload.get("event_type", "unknown"),
                "squad_id": payload.get("squad_id", "unknown"),
                "agent_name": payload.get("source_agent", "unknown"),
                "reason": escalation_reason,
                "confidence_score": confidence,
                "context_payload": json.dumps(self._safe_context(payload)),
                "agent_rationale": payload.get("rationale", ""),
                "priority": self._derive_priority(confidence, guard_failed),
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
                f"confidence={confidence:.2f} guard_failed={guard_failed} priority={ticket['priority']}"
            )
        else:
            ticket = {}
            self.logger.info(
                f"[{self.layer}] No escalation needed: confidence={confidence:.2f} >= {self._threshold}"
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

    def _build_reason(self, confidence: float, guard_failed: bool, forced: bool) -> str:
        reasons = []
        if forced:
            reasons.append("forced escalation requested")
        if confidence < self._threshold:
            reasons.append(f"confidence {confidence:.2f} below threshold {self._threshold}")
        if guard_failed:
            reasons.append("guard check failed (PII or policy violation)")
        return "; ".join(reasons) if reasons else "unknown"

    def _derive_priority(self, confidence: float, guard_failed: bool) -> str:
        if guard_failed or confidence < 0.3:
            return "critical"
        if confidence < 0.5:
            return "high"
        if confidence < self._threshold:
            return "normal"
        return "low"

    def _safe_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe_keys = [
            "claim_id", "event_id", "event_type", "squad_id",
            "priority", "claim_type", "decision", "confidence",
            "completeness_score", "coverage_match", "correlation_id",
        ]
        return {k: payload[k] for k in safe_keys if k in payload}
