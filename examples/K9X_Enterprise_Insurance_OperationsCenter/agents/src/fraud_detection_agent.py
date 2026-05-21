# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_fraud_detection_agent (SBB)
#
# Responsibilities:
#   - Correlate risk signals across multiple data sources
#   - Match against watchlist / known fraud patterns
#   - Flag anomalies (amount spikes, repeat claimants, suspicious timing)
#   - Produce RiskAssessmentRecord with risk score and signals

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_insert_ignore


FRAUD_SIGNAL_KEYWORDS = [
    "multiple claims", "duplicate", "suspicious", "rapid succession",
    "inflated", "staged", "fictitious", "phantom provider", "kickback",
]

RISK_SCORE_HIGH = 0.8
RISK_SCORE_MEDIUM = 0.5


class FraudDetectionAgent(BaseAgent):
    """
    SBB: k9_sbb_fraud_detection_agent

    Risk signal correlation, watchlist matching, anomaly flagging.
    Routes to reasoning-capable model (Granite 3.x) via EOCModelRouter.
    """

    layer = "EOC FraudDetection SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_id = payload.get("event_id") or str(uuid.uuid4())

        rule_signals = self._apply_rule_signals(payload)
        rule_score = self._score_from_rules(rule_signals)

        llm_signals: List[str] = []
        llm_score = 0.0
        recommendation = "monitor"

        context = self._build_context(payload)
        prompt = (
            f"You are an insurance fraud detection AI. Analyze this signal:\n\n"
            f"{context}\n\n"
            f"Known rule-based signals detected: {rule_signals}\n\n"
            f"Respond with:\n"
            f"RISK_SCORE: <0.0-1.0>\n"
            f"SIGNALS: <comma-separated fraud indicators>\n"
            f"RECOMMENDATION: <monitor|flag|block|escalate>\n"
            f"RATIONALE: <2-3 sentence analysis>"
        )
        req = InferenceRequest(
            prompt=prompt,
            task_type="fraud",
            metadata={"agent": "FraudDetectionAgent", "correlation_id": correlation_id},
        )
        resp = llm_invoke(self.config, req)
        raw = (resp.output or "").strip()
        llm_score, llm_signals, recommendation, rationale = self._parse_response(raw)

        self.logger.info(
            f"[{self.layer}] Fraud analysis: risk={llm_score:.2f} "
            f"signals={len(llm_signals)} rec={recommendation} model={resp.model_alias}"
        )

        final_score = max(rule_score, llm_score)
        all_signals = list(set(rule_signals + llm_signals))

        result = {
            "agent": "FraudDetectionAgent",
            "event_id": event_id,
            "correlation_id": correlation_id,
            "risk_score": final_score,
            "signals": all_signals,
            "rule_signals": rule_signals,
            "recommendation": recommendation,
            "rationale": rationale if "rationale" in dir() else "",
            "confidence": 1.0 - (0.1 * len([s for s in all_signals if "uncertain" in s])),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        self._persist(payload, result)

        self.publish_event({
            "type": "FraudAssessmentCompleted",
            "correlation_id": correlation_id,
            "risk_score": final_score,
            "recommendation": recommendation,
        })

        return result

    # ------------------------------------------------------------------
    def _persist(self, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
        import json as _json
        try:
            alert_id = f"ALT-{uuid.uuid4().hex[:12].upper()}"
            with pg_connect(self.config) as conn:
                pg_insert_ignore(conn, "eoc.incident_alerts", {
                    "alert_id":        alert_id,
                    "alert_type":      "fraud_signal",
                    "source":          payload.get("alert_source", "FraudDetectionAgent"),
                    "severity":        payload.get("severity", "medium"),
                    "description":     payload.get("description", ""),
                    "risk_score":      result.get("risk_score", 0.0),
                    "related_claim_id": payload.get("claim_id"),
                    "status":          "open",
                    "correlation_id":  result.get("correlation_id"),
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
        score = 0.5
        signals = []
        recommendation = "monitor"
        rationale = raw

        for line in raw.splitlines():
            lower = line.lower()
            if lower.startswith("risk_score:"):
                try:
                    score = float(line.split(":", 1)[1].strip())
                    score = max(0.0, min(1.0, score))
                except ValueError:
                    pass
            elif lower.startswith("signals:"):
                val = line.split(":", 1)[1].strip()
                signals = [s.strip() for s in val.split(",") if s.strip() and s.strip().lower() != "none"]
            elif lower.startswith("recommendation:"):
                recommendation = line.split(":", 1)[1].strip().lower()
            elif lower.startswith("rationale:"):
                rationale = line.split(":", 1)[1].strip()

        return score, signals, recommendation, rationale
