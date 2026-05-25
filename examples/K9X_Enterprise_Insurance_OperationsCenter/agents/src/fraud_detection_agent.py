# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_fraud_detection_agent (SBB)
#
# Responsibilities:
#   - Correlate risk signals across multiple data sources
#   - Match against watchlist / known fraud patterns
#   - Flag anomalies (amount spikes, repeat claimants, suspicious timing)
#   - Produce RiskAssessmentRecord with risk score and signals
#
# Extends K9ValidationLoopAgent — iterates until risk confidence is sufficient
# or until escalation/clear-negative is reached.

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_agents.validation import (
    K9ValidationLoopAgent,
    ValidationDisposition,
    ValidationLoopContext,
    ValidationLoopResult,
)
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_insert_ignore


FRAUD_SIGNAL_KEYWORDS = [
    "multiple claims", "duplicate", "suspicious", "rapid succession",
    "inflated", "staged", "fictitious", "phantom provider", "kickback",
]

RISK_SCORE_HIGH   = 0.8
RISK_SCORE_MEDIUM = 0.5


class FraudDetectionAgent(K9ValidationLoopAgent):
    """
    SBB: k9_sbb_fraud_detection_agent

    Iterative fraud signal correlation — each iteration refines the hypothesis
    using prior signals and LLM rationale until risk confidence is sufficient.

    Loop:
        generate_hypothesis  — accumulate rule signals + prior iteration context
        run_validation       — LLM analysis with accumulated signals as context
        evaluate_observation — combine rule score + LLM score → confidence
        should_continue      — FINALIZE on high risk, FAIL on clear negative,
                               ESCALATE on LLM request, CONTINUE otherwise
        finalize             — persist, publish, return aggregated result
    """

    layer = "EOC FraudDetection SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready")

    # ------------------------------------------------------------------
    # Validation loop — five domain methods
    # ------------------------------------------------------------------

    def generate_hypothesis(self, loop_ctx: ValidationLoopContext) -> Dict[str, Any]:
        accumulated_signals: List[str] = []
        prior_rationale: List[str] = []
        for step in loop_ctx.steps:
            accumulated_signals.extend(step.observation.get("signals", []))
            rationale = step.observation.get("rationale", "")
            if rationale:
                prior_rationale.append(f"Iteration {step.iteration}: {rationale}")

        rule_signals = self._apply_rule_signals(loop_ctx.payload)
        all_signals  = list(set(rule_signals + accumulated_signals))

        return {
            "payload":        loop_ctx.payload,
            "rule_signals":   all_signals,
            "rule_score":     self._score_from_rules(all_signals),
            "prior_rationale": prior_rationale,
        }

    def run_validation(self, hypothesis: Dict[str, Any], loop_ctx: ValidationLoopContext) -> Dict[str, Any]:
        payload      = hypothesis["payload"]
        rule_signals = hypothesis["rule_signals"]
        prior_ctx    = ""
        if hypothesis["prior_rationale"]:
            prior_ctx = "\n\nPrior analysis:\n" + "\n".join(
                f"- {r}" for r in hypothesis["prior_rationale"]
            )

        context = self._build_context(payload)
        prompt  = (
            f"You are an insurance fraud detection AI. Analyze this signal:\n\n"
            f"{context}\n\n"
            f"Known rule-based signals detected: {rule_signals}"
            f"{prior_ctx}\n\n"
            f"Respond with:\n"
            f"RISK_SCORE: <0.0-1.0>\n"
            f"SIGNALS: <comma-separated fraud indicators>\n"
            f"RECOMMENDATION: <monitor|flag|block|escalate>\n"
            f"RATIONALE: <2-3 sentence analysis>"
        )
        req  = InferenceRequest(
            prompt=prompt,
            task_type="fraud",
            metadata={"agent": self.layer, "iteration": loop_ctx.iteration},
        )
        resp = llm_invoke(self.config, req)
        return {
            "rule_signals": rule_signals,
            "rule_score":   hypothesis["rule_score"],
            "llm_output":   (resp.output or "").strip(),
            "model_alias":  resp.model_alias,
        }

    def evaluate_observation(self, tool_result: Dict[str, Any], loop_ctx: ValidationLoopContext) -> Dict[str, Any]:
        llm_score, llm_signals, recommendation, rationale = self._parse_response(tool_result["llm_output"])
        final_score = max(tool_result["rule_score"], llm_score)
        all_signals = list(set(tool_result["rule_signals"] + llm_signals))

        self.logger.info(
            "[%s] Iteration %d: risk=%.2f signals=%d rec=%s model=%s",
            self.layer, loop_ctx.iteration, final_score,
            len(all_signals), recommendation, tool_result.get("model_alias", ""),
        )

        return {
            "risk_score":     final_score,
            "signals":        all_signals,
            "recommendation": recommendation,
            "rationale":      rationale,
            "confidence":     final_score,   # risk score is the confidence signal for fraud
            "model_alias":    tool_result.get("model_alias", ""),
        }

    def should_continue(self, observation: Dict[str, Any], loop_ctx: ValidationLoopContext) -> ValidationDisposition:
        risk_score     = observation["risk_score"]
        recommendation = observation["recommendation"]

        if risk_score >= RISK_SCORE_HIGH:
            return ValidationDisposition.FINALIZE

        if risk_score < 0.2 and not observation["signals"]:
            return ValidationDisposition.FAIL     # clear negative — not fraud

        if recommendation == "escalate":
            return ValidationDisposition.ESCALATE

        return ValidationDisposition.CONTINUE

    def finalize(self, loop_ctx: ValidationLoopContext) -> ValidationLoopResult:
        correlation_id = loop_ctx.payload.get("correlation_id") or str(uuid.uuid4())
        event_id       = loop_ctx.payload.get("event_id")       or str(uuid.uuid4())

        all_signals: List[str] = []
        for step in loop_ctx.steps:
            all_signals.extend(step.observation.get("signals", []))
        all_signals = list(set(all_signals))

        last = loop_ctx.steps[-1] if loop_ctx.steps else None
        obs  = last.observation if last else {}

        result = {
            "agent":          "FraudDetectionAgent",
            "event_id":        event_id,
            "correlation_id":  correlation_id,
            "risk_score":      obs.get("risk_score", 0.0),
            "signals":         all_signals,
            "rule_signals":    loop_ctx.steps[0].observation.get("signals", []) if loop_ctx.steps else [],
            "recommendation":  obs.get("recommendation", "monitor"),
            "rationale":       obs.get("rationale", ""),
            "confidence":      last.confidence if last else 0.0,
            "iterations":      loop_ctx.iteration,
            "timestamp_utc":   datetime.now(timezone.utc).isoformat(),
        }

        self._persist(loop_ctx.payload, result)
        self.publish_event({
            "type":           "FraudAssessmentCompleted",
            "correlation_id":  correlation_id,
            "risk_score":      result["risk_score"],
            "recommendation":  result["recommendation"],
        })

        return ValidationLoopResult(
            disposition      = ValidationDisposition.FINALIZE,
            output           = result,
            steps            = loop_ctx.steps,
            iterations       = loop_ctx.iteration,
            final_confidence = last.confidence if last else 0.0,
            evidence         = [s.observation.get("rationale", "") for s in loop_ctx.steps],
        )

    def fail(self, loop_ctx: ValidationLoopContext) -> ValidationLoopResult:
        """Clear negative — no fraud signals detected."""
        correlation_id = loop_ctx.payload.get("correlation_id") or str(uuid.uuid4())
        last = loop_ctx.steps[-1] if loop_ctx.steps else None
        obs  = last.observation if last else {}

        output = {
            "agent":          "FraudDetectionAgent",
            "correlation_id":  correlation_id,
            "risk_score":      obs.get("risk_score", 0.0),
            "signals":         [],
            "recommendation":  "clear",
            "rationale":       obs.get("rationale", "No fraud signals detected."),
            "confidence":      last.confidence if last else 0.0,
            "iterations":      loop_ctx.iteration,
            "timestamp_utc":   datetime.now(timezone.utc).isoformat(),
        }
        return ValidationLoopResult(
            disposition      = ValidationDisposition.FAIL,
            output           = output,
            steps            = loop_ctx.steps,
            iterations       = loop_ctx.iteration,
            final_confidence = last.confidence if last else 0.0,
        )

    def escalate(self, loop_ctx: ValidationLoopContext) -> ValidationLoopResult:
        """Unresolvable uncertainty — route to human review."""
        correlation_id = loop_ctx.payload.get("correlation_id") or str(uuid.uuid4())
        last = loop_ctx.steps[-1] if loop_ctx.steps else None
        obs  = last.observation if last else {}

        all_signals: List[str] = []
        for step in loop_ctx.steps:
            all_signals.extend(step.observation.get("signals", []))

        output = {
            "agent":          "FraudDetectionAgent",
            "correlation_id":  correlation_id,
            "risk_score":      obs.get("risk_score", 0.0),
            "signals":         list(set(all_signals)),
            "recommendation":  "escalate",
            "rationale":       obs.get("rationale", "Escalated for human review."),
            "confidence":      last.confidence if last else 0.0,
            "iterations":      loop_ctx.iteration,
            "timestamp_utc":   datetime.now(timezone.utc).isoformat(),
        }
        return ValidationLoopResult(
            disposition      = ValidationDisposition.ESCALATE,
            output           = output,
            steps            = loop_ctx.steps,
            iterations       = loop_ctx.iteration,
            final_confidence = last.confidence if last else 0.0,
        )

    # ------------------------------------------------------------------
    # _to_dict override — merge output into top level so downstream agents
    # that read fraud_assessment.risk_score continue to work unchanged.
    # New fields (disposition, iterations, steps) appear alongside.
    # ------------------------------------------------------------------

    def _to_dict(self, result: ValidationLoopResult) -> Dict[str, Any]:
        base = super()._to_dict(result)
        return {**base, **base.get("output", {})}

    # ------------------------------------------------------------------
    # Helpers (unchanged from original one-shot implementation)
    # ------------------------------------------------------------------

    def _persist(self, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
        import json as _json
        try:
            alert_id = f"ALT-{uuid.uuid4().hex[:12].upper()}"
            with pg_connect(self.config) as conn:
                pg_insert_ignore(conn, "eoc.incident_alerts", {
                    "alert_id":         alert_id,
                    "alert_type":       "fraud_signal",
                    "source":           payload.get("alert_source", "FraudDetectionAgent"),
                    "severity":         payload.get("severity", "medium"),
                    "description":      payload.get("description", ""),
                    "risk_score":       result.get("risk_score", 0.0),
                    "related_claim_id": payload.get("claim_id"),
                    "status":           "open",
                    "correlation_id":   result.get("correlation_id"),
                }, "alert_id")
                conn.commit()
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] PG persist failed: {exc}")

    def _apply_rule_signals(self, payload: Dict[str, Any]) -> List[str]:
        signals = []
        text = " ".join(str(v) for v in payload.values() if isinstance(v, str)).lower()

        for keyword in FRAUD_SIGNAL_KEYWORDS:
            if keyword in text:
                signals.append(f"keyword:{keyword}")

        amount = float(payload.get("amount_claimed", 0))
        if amount > 500_000:
            signals.append("amount:extremely_high_value")
        elif amount > 100_000:
            signals.append("amount:high_value")

        if payload.get("is_repeat_claimant"):
            signals.append("claimant:repeat_filer")

        return signals

    def _score_from_rules(self, signals: List[str]) -> float:
        if not signals:
            return 0.0
        score = min(0.3 * len(signals), 0.9)
        if any("extremely_high" in s for s in signals):
            score = max(score, RISK_SCORE_HIGH)
        return round(score, 2)

    def _build_context(self, payload: Dict[str, Any]) -> str:
        parts = [
            f"Claimant ID: {payload.get('claimant_id', 'unknown')}",
            f"Claim Type: {payload.get('claim_type', 'unknown')}",
            f"Amount Claimed: ${float(payload.get('amount_claimed', 0)):,.2f}",
            f"Alert Source: {payload.get('alert_source', 'unknown')}",
            f"Alert Description: {payload.get('description', 'none')}",
        ]
        return "\n".join(parts)

    def _parse_response(self, raw: str):
        score          = 0.5
        signals        = []
        recommendation = "monitor"
        rationale      = raw

        for line in raw.splitlines():
            lower = line.lower()
            if lower.startswith("risk_score:"):
                try:
                    score = float(line.split(":", 1)[1].strip())
                    score = max(0.0, min(1.0, score))
                except ValueError:
                    pass
            elif lower.startswith("signals:"):
                val     = line.split(":", 1)[1].strip()
                signals = [s.strip() for s in val.split(",") if s.strip() and s.strip().lower() != "none"]
            elif lower.startswith("recommendation:"):
                recommendation = line.split(":", 1)[1].strip().lower()
            elif lower.startswith("rationale:"):
                rationale = line.split(":", 1)[1].strip()

        return score, signals, recommendation, rationale
