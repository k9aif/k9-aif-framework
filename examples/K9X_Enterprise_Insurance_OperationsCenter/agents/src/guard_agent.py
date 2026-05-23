# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_guard_agent (SBB)
#
# Responsibilities:
#   - Pre-inference PII detection and tokenization (Pseudonymization pattern)
#   - Deterministic SHA-256 token generation — same raw value always maps to the
#     same token, enabling downstream reference without exposing the plaintext.
#   - Per-run token vault: raw values never leave this method; only opaque tokens
#     are forwarded to the LLM (RAG principle — keep raw PII in the vault, not
#     in agent context).
#   - Post-inference output validation (schema + policy check)
#   - Policy enforcement gate — blocks non-compliant outputs
#   - Emits governance events for audit trail

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke


PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{16}\b", "CREDIT_CARD"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "EMAIL"),
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "PHONE"),
]


def _pii_token(pii_type: str, raw_value: str) -> str:
    """
    Deterministic pseudonymization (pattern 2 from architecture guidelines).

    SHA-256 of the raw value → first 8 hex chars as the token suffix.
    Same input always produces the same token (stable reference across runs),
    but the raw value is never embedded in or derivable from the token.
    """
    digest = hashlib.sha256(raw_value.encode()).hexdigest()[:8].upper()
    return f"{pii_type}-TKN-{digest}"


class GuardAgent(BaseAgent):
    """
    SBB: k9_sbb_guard_agent

    Pre/post inference governance: PII detection, tokenization, policy enforcement.

    PII Handling Architecture (three-pattern implementation):

    1. Tokenization / Pseudonymization — detected PII is replaced with a
       deterministic opaque token (e.g. SSN-TKN-A3F29B01) before any text
       reaches the LLM. The token vault maps token → PII type only; raw values
       are never persisted or forwarded.

    2. Deterministic SHA-256 hashing — _pii_token() uses SHA-256 so the same
       SSN always maps to the same token. This allows downstream agents to
       correlate references (e.g. "SSN-TKN-A3F29B01 appeared in two documents")
       without ever seeing the plaintext.

    3. RAG / vault isolation — the token vault is opaque to every downstream
       agent. Only GuardAgent holds the token→type mapping (not the raw value).
       In production this vault would live in a KMS-backed secure store; here
       it is scoped to the single request lifetime and returned as audit metadata.

    Hard requirement — no fallback model accepted for compliance tasks.
    """

    layer = "EOC Guard SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Ready (Guardian mode — tokenization active)")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        mode = payload.get("guard_mode", "pre")  # pre | post | full

        text_to_scan = self._extract_text(payload)
        pii_findings, tokenized_text, token_vault = self._tokenize_pii(text_to_scan)

        policy_violations = []
        guardian_output = ""
        passed = True

        if text_to_scan:
            # LLM sees only tokenized text — raw PII never reaches the model
            prompt = (
                f"You are an AI safety guardrail. Check this content for:\n"
                f"1. Remaining Personal Identifiable Information (PII) — note: known PII has "
                f"already been replaced with opaque tokens (e.g. SSN-TKN-XXXXXXXX)\n"
                f"2. Policy violations (fraud indicators, prohibited content)\n"
                f"3. Output quality issues\n\n"
                f"Content:\n{tokenized_text[:2000]}\n\n"
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
                f"tokens_issued={len(token_vault)} violations={len(policy_violations)} "
                f"model={resp.model_alias}"
            )

        result = {
            "agent": "GuardAgent",
            "correlation_id": correlation_id,
            "guard_mode": mode,
            "passed": passed,
            "pii_detected": len(pii_findings) > 0,
            "pii_findings": pii_findings,
            "policy_violations": policy_violations,
            # tokenized_text replaces masked_text — raw PII is gone, tokens remain
            "tokenized_text": tokenized_text if pii_findings else None,
            # vault exposes token→type only (never raw value) — safe for audit log
            "token_vault": token_vault,
            "guardian_output": guardian_output,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        self.publish_event({
            "type": "GuardCheckCompleted",
            "agent": "GuardAgent",
            "correlation_id": correlation_id,
            "passed": passed,
            "pii_detected": len(pii_findings) > 0,
            "tokens_issued": len(token_vault),
        })

        return result

    # ------------------------------------------------------------------
    def _extract_text(self, payload: Dict[str, Any]) -> str:
        parts = []
        for key in ("raw_text", "notes", "rationale", "extracted_text", "content", "description",
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
                # scan LLM-extracted fields one level deeper (e.g. extraction.extracted_fields)
                extracted_fields = nested.get("extracted_fields", {})
                if isinstance(extracted_fields, dict):
                    for field in ("description", "claimant_name", "provider"):
                        val = extracted_fields.get(field)
                        if val:
                            parts.append(str(val))
        return " ".join(parts)

    def _tokenize_pii(
        self, text: str
    ) -> Tuple[List[Dict], str, List[Dict]]:
        """
        Detect PII, replace each occurrence with a deterministic opaque token,
        and build a token vault (token → type only, no raw values).

        Returns:
            pii_findings  — [{type, count}] summary for compliance reporting
            tokenized_text — text safe to forward to LLM
            token_vault    — [{token, pii_type}] for audit metadata (no raw values)
        """
        findings = []
        tokenized = text
        vault: Dict[str, str] = {}  # token → pii_type

        for pattern, pii_type in PII_PATTERNS:
            matches = re.findall(pattern, tokenized)
            if not matches:
                continue
            findings.append({"type": pii_type, "count": len(matches)})

            def _replace(m: re.Match, _type: str = pii_type) -> str:
                tok = _pii_token(_type, m.group(0))
                vault[tok] = _type
                return tok

            tokenized = re.sub(pattern, _replace, tokenized)

        vault_list = [{"token": tok, "pii_type": pii_type} for tok, pii_type in vault.items()]
        return findings, tokenized, vault_list

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
