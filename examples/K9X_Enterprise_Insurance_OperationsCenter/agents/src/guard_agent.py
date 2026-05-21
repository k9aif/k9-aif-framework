# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_guard_agent (SBB)
#
# Responsibilities:
#   - Pre-inference PII detection and masking (via Granite Guardian)
#   - Post-inference output validation (schema + policy check)
#   - Policy enforcement gate — blocks non-compliant outputs
#   - Emits governance events for audit trail

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke


PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{16}\b", "CREDIT_CARD"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "EMAIL"),
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "PHONE"),
]


class GuardAgent(BaseAgent):
    """
    SBB: k9_sbb_guard_agent

    Pre/post inference governance: PII detection, output validation, policy enforcement.
    Routes to Granite Guardian for AI-based policy checks.
    Hard requirement — no fallback model accepted for compliance tasks.
    """

    layer = "EOC Guard SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready (Guardian mode)")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        mode = payload.get("guard_mode", "pre")  # pre | post | full

        text_to_scan = self._extract_text(payload)
        pii_findings = self._pattern_scan(text_to_scan)
        masked_text = self._mask_pii(text_to_scan, pii_findings)

        policy_violations = []
        guardian_output = ""
        passed = True

        if text_to_scan:
            prompt = (
                f"You are an AI safety guardrail. Check this content for:\n"
                f"1. Personal Identifiable Information (PII)\n"
                f"2. Policy violations (fraud indicators, prohibited content)\n"
                f"3. Output quality issues\n\n"
                f"Content:\n{masked_text[:2000]}\n\n"
                f"Respond with:\n"
                f"PII_DETECTED: <yes|no>\n"
                f"VIOLATIONS: <comma-separated list or 'none'>\n"
                f"PASSED: <yes|no>\n"
                f"REASON: <brief explanation>"
            )
            req = InferenceRequest(
                prompt=prompt,
                task_type="guardrails",
                sensitivity="confidential",
                metadata={"agent": "GuardAgent", "correlation_id": correlation_id},
            )
            resp = llm_invoke(self.config, req)
            guardian_output = (resp.output or "").strip()
            policy_violations, passed = self._parse_guardian_output(guardian_output, pii_findings)

            self.logger.info(
                f"[{self.layer}] Guard check: passed={passed} pii={len(pii_findings)} "
                f"violations={len(policy_violations)} model={resp.model_alias}"
            )

        result = {
            "agent": "GuardAgent",
            "correlation_id": correlation_id,
            "guard_mode": mode,
            "passed": passed,
            "pii_detected": len(pii_findings) > 0,
            "pii_findings": pii_findings,
            "policy_violations": policy_violations,
            "masked_text": masked_text if pii_findings else None,
            "guardian_output": guardian_output,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        self.publish_event({
            "type": "GuardCheckCompleted",
            "agent": "GuardAgent",
            "correlation_id": correlation_id,
            "passed": passed,
            "pii_detected": len(pii_findings) > 0,
        })

        return result

    # ------------------------------------------------------------------
    def _extract_text(self, payload: Dict[str, Any]) -> str:
        parts = []
        for key in ("notes", "rationale", "extracted_text", "content", "description",
                    "recommendation", "customer_message", "change_description"):
            val = payload.get(key)
            if val:
                parts.append(str(val))
        # also scan text from accumulated agent results in the context
        for result_key in ("triage", "adjudication", "fraud_assessment", "extraction",
                           "intent", "impact_assessment"):
            nested = payload.get(result_key, {})
            if isinstance(nested, dict):
                for field in ("rationale", "triage_reasoning", "extracted_text", "description"):
                    val = nested.get(field)
                    if val:
                        parts.append(str(val))
        return " ".join(parts)

    def _pattern_scan(self, text: str):
        findings = []
        for pattern, label in PII_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                findings.append({"type": label, "count": len(matches)})
        return findings

    def _mask_pii(self, text: str, findings) -> str:
        masked = text
        for pattern, label in PII_PATTERNS:
            masked = re.sub(pattern, f"[{label}_REDACTED]", masked)
        return masked

    def _parse_guardian_output(self, raw: str, pii_findings):
        violations = []
        passed = True

        for line in raw.splitlines():
            lower = line.lower()
            if lower.startswith("violations:"):
                val = line.split(":", 1)[1].strip()
                if val.lower() not in ("none", "", "no"):
                    violations = [v.strip() for v in val.split(",") if v.strip()]
            elif lower.startswith("passed:"):
                val = line.split(":", 1)[1].strip().lower()
                passed = val in ("yes", "true", "1")

        if pii_findings:
            passed = False

        return violations, passed
