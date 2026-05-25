# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_document_extractor_agent (SBB)
#
# Responsibilities:
#   - Receive raw document payload (text or file path)
#   - Apply OCR pre-processing via Tesseract (when available)
#   - Use LLM (Granite Code / extraction model) for structured extraction
#   - Validate extracted output against expected schema
#   - Return structured DocumentRecord
#
# Extends K9ValidationLoopAgent — iterates if extraction confidence is low
# or required fields are missing, refining the prompt on each attempt.

import uuid
import re
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
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_upsert

_REQUIRED_FIELDS = ("document_type", "claimant_name", "policy_number")


class DocumentExtractorAgent(K9ValidationLoopAgent):
    """
    SBB: k9_sbb_document_extractor_agent

    OCR pipeline: ingestion → extraction → structured output → validation.
    Iterates if required fields are missing or extraction confidence is low,
    refining the prompt each time based on what was not found.

    Loop:
        generate_hypothesis  — build targeted extraction prompt; highlight
                               missing fields from prior attempts
        run_validation       — OCR (first iteration only) + LLM extraction
        evaluate_observation — parse JSON, score confidence by field coverage
        should_continue      — FINALIZE when required fields extracted,
                               CONTINUE with refined prompt otherwise
        finalize             — persist to PG, publish event, return result
    """

    layer = "EOC DocumentExtractor SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self._tesseract_available = self._check_tesseract()
        self._raw_text_cache: Optional[str] = None   # OCR runs once, cached
        self.logger.info(f"[{self.layer}] Ready, Tesseract={self._tesseract_available}")

    # ------------------------------------------------------------------
    # Validation loop — five domain methods
    # ------------------------------------------------------------------

    def generate_hypothesis(self, loop_ctx: ValidationLoopContext) -> Dict[str, Any]:
        # OCR on first iteration only — cache the result
        if loop_ctx.iteration == 1:
            raw_text = loop_ctx.payload.get("raw_text", "")
            file_path = loop_ctx.payload.get("file_path")
            if not raw_text and file_path:
                raw_text = self._ocr_extract(file_path)
            if not raw_text:
                raw_text = loop_ctx.payload.get("content", "")
            self._raw_text_cache = raw_text
        else:
            raw_text = self._raw_text_cache or ""

        # Find missing required fields from prior attempts
        missing: List[str] = []
        if loop_ctx.steps:
            last_extracted = loop_ctx.steps[-1].observation.get("extracted_fields", {})
            missing = [f for f in _REQUIRED_FIELDS if not last_extracted.get(f)]

        focus = ""
        if missing:
            focus = (
                f"\n\nFocus especially on extracting these missing fields: {missing}. "
                f"Look for them even if they appear in an unusual format or location."
            )

        return {
            "raw_text":  raw_text,
            "focus":     focus,
            "iteration": loop_ctx.iteration,
        }

    def run_validation(self, hypothesis: Dict[str, Any], loop_ctx: ValidationLoopContext) -> str:
        raw_text = hypothesis["raw_text"]
        focus    = hypothesis["focus"]

        if not raw_text:
            return "{}"

        prompt = (
            f"Extract structured information from this insurance document:\n\n"
            f"{raw_text[:3000]}"
            f"{focus}\n\n"
            f"Return JSON with these fields (use null if not found):\n"
            f'{{"document_type": "", "claimant_name": "", "policy_number": "",'
            f'"claim_number": "", "incident_date": "", "amount": null,'
            f'"provider": "", "description": "", "signatures_present": false}}'
        )
        req  = InferenceRequest(
            prompt=prompt,
            task_type="extraction",
            metadata={"agent": self.layer, "iteration": loop_ctx.iteration},
        )
        resp = llm_invoke(self.config, req)
        return (resp.output or "").strip()

    def evaluate_observation(self, tool_result: str, loop_ctx: ValidationLoopContext) -> Dict[str, Any]:
        structured = self._parse_json_output(tool_result)

        # Confidence = fraction of required fields successfully extracted
        extracted_required = [f for f in _REQUIRED_FIELDS if structured.get(f)]
        confidence = len(extracted_required) / len(_REQUIRED_FIELDS) if _REQUIRED_FIELDS else 0.0

        classification    = structured.get("document_type", "unknown")
        validation_status = "valid" if structured else "parse_failed"

        self.logger.info(
            "[%s] Iteration %d: fields=%d/%d confidence=%.2f type=%s",
            self.layer, loop_ctx.iteration,
            len(extracted_required), len(_REQUIRED_FIELDS),
            confidence, classification,
        )

        return {
            "extracted_fields":  structured,
            "classification":    classification,
            "validation_status": validation_status,
            "confidence":        confidence,
            "missing_required":  [f for f in _REQUIRED_FIELDS if not structured.get(f)],
        }

    def should_continue(self, observation: Dict[str, Any], loop_ctx: ValidationLoopContext) -> ValidationDisposition:  # noqa: ARG002
        # All required fields extracted — done
        if not observation["missing_required"]:
            return ValidationDisposition.FINALIZE

        # If no text was available there is nothing more to try
        if not self._raw_text_cache:
            return ValidationDisposition.FINALIZE

        return ValidationDisposition.CONTINUE

    def finalize(self, loop_ctx: ValidationLoopContext) -> ValidationLoopResult:
        correlation_id = loop_ctx.payload.get("correlation_id") or str(uuid.uuid4())
        document_id    = loop_ctx.payload.get("document_id") or f"DOC-{uuid.uuid4().hex[:8].upper()}"
        file_path      = loop_ctx.payload.get("file_path")

        last = loop_ctx.steps[-1] if loop_ctx.steps else None
        obs  = last.observation if last else {}

        result = {
            "agent":             "DocumentExtractorAgent",
            "document_id":        document_id,
            "correlation_id":     correlation_id,
            "classification":     obs.get("classification", "unknown"),
            "extracted_fields":   obs.get("extracted_fields", {}),
            "raw_text_length":    len(self._raw_text_cache or ""),
            "validation_status":  obs.get("validation_status", "skipped"),
            "ocr_applied":        bool(file_path and self._tesseract_available),
            "iterations":         loop_ctx.iteration,
            "timestamp_utc":      datetime.now(timezone.utc).isoformat(),
        }

        self._persist(loop_ctx.payload, result)
        self.publish_event({
            "type":              "DocumentExtractionCompleted",
            "document_id":        document_id,
            "correlation_id":     correlation_id,
            "classification":     result["classification"],
            "validation_status":  result["validation_status"],
        })

        return ValidationLoopResult(
            disposition      = ValidationDisposition.FINALIZE,
            output           = result,
            steps            = loop_ctx.steps,
            iterations       = loop_ctx.iteration,
            final_confidence = last.confidence if last else 0.0,
            evidence         = [
                f"Iteration {s.iteration}: extracted {len(s.observation.get('extracted_fields', {}))} fields"
                for s in loop_ctx.steps
            ],
        )

    # ------------------------------------------------------------------
    # _to_dict override — merge output into top level so downstream agents
    # that read extraction.extracted_fields continue to work unchanged.
    # ------------------------------------------------------------------

    def _to_dict(self, result: ValidationLoopResult) -> Dict[str, Any]:
        base = super()._to_dict(result)
        return {**base, **base.get("output", {})}

    # ------------------------------------------------------------------
    # Helpers (unchanged from original one-shot implementation)
    # ------------------------------------------------------------------

    def _persist(self, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
        try:
            with pg_connect(self.config) as conn:
                pg_upsert(conn, "eoc.documents", {
                    "document_id":       result["document_id"],
                    "claim_id":          payload.get("claim_id"),
                    "claimant_id":       payload.get("claimant_id"),
                    "filename":          payload.get("filename", "unknown"),
                    "file_type":         payload.get("file_type"),
                    "ocr_status":        "done" if result.get("ocr_applied") else "skipped",
                    "extracted_text":    (self._raw_text_cache or "")[:4000],
                    "classification":    result.get("classification"),
                    "validation_status": result.get("validation_status"),
                    "correlation_id":    result.get("correlation_id"),
                }, "document_id")
                conn.commit()
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] PG persist failed: {exc}")

    def _check_tesseract(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=3)
            return result.returncode == 0
        except Exception:
            return False

    def _ocr_extract(self, file_path: str) -> str:
        if not self._tesseract_available:
            self.logger.warning(f"[{self.layer}] Tesseract not available for {file_path}")
            return ""
        try:
            import subprocess
            result = subprocess.run(
                ["tesseract", file_path, "stdout", "-l", "eng"],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout.strip()
        except Exception as exc:
            self.logger.error(f"[{self.layer}] OCR failed for {file_path}: {exc}")
            return ""

    def _parse_json_output(self, raw: str) -> Dict[str, Any]:
        import json
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        return {}
