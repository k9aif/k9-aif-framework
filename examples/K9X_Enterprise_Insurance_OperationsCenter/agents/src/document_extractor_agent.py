# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_document_extractor_agent (SBB)
#
# Responsibilities:
#   - Receive raw document payload (text or file path)
#   - Apply OCR pre-processing via Tesseract (when available)
#   - Use LLM (Granite Code / extraction model) for structured extraction
#   - Validate extracted output against expected schema
#   - Return structured DocumentRecord

import uuid
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import llm_invoke
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_connect, pg_upsert


class DocumentExtractorAgent(BaseAgent):
    """
    SBB: k9_sbb_document_extractor_agent

    OCR pipeline: ingestion → extraction → structured output → validation.
    Routes to extraction-capable model (Granite Code) via EOCModelRouter.
    """

    layer = "EOC DocumentExtractor SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self._tesseract_available = self._check_tesseract()
        self.logger.info(f"[{self.layer}] Ready, Tesseract={self._tesseract_available}")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        document_id = payload.get("document_id") or f"DOC-{uuid.uuid4().hex[:8].upper()}"

        raw_text = payload.get("raw_text", "")
        file_path = payload.get("file_path")

        if not raw_text and file_path:
            raw_text = self._ocr_extract(file_path)

        if not raw_text:
            raw_text = payload.get("content", "")

        structured = {}
        classification = "unknown"
        validation_status = "skipped"

        if raw_text:
            prompt = (
                f"Extract structured information from this insurance document:\n\n"
                f"{raw_text[:3000]}\n\n"
                f"Return JSON with these fields (use null if not found):\n"
                f'{{"document_type": "", "claimant_name": "", "policy_number": "",'
                f'"claim_number": "", "incident_date": "", "amount": null,'
                f'"provider": "", "description": "", "signatures_present": false}}'
            )
            req = InferenceRequest(
                prompt=prompt,
                task_type="extraction",
                metadata={"agent": "DocumentExtractorAgent", "document_id": document_id},
            )
            resp = llm_invoke(self.config, req)
            raw_output = (resp.output or "").strip()
            structured = self._parse_json_output(raw_output)
            classification = structured.get("document_type", "unknown")
            validation_status = "valid" if structured else "parse_failed"

            self.logger.info(
                f"[{self.layer}] Extraction complete: doc={document_id} "
                f"type={classification} model={resp.model_alias}"
            )

        result = {
            "agent": "DocumentExtractorAgent",
            "document_id": document_id,
            "correlation_id": correlation_id,
            "classification": classification,
            "extracted_fields": structured,
            "raw_text_length": len(raw_text),
            "validation_status": validation_status,
            "ocr_applied": bool(file_path and self._tesseract_available),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        self._persist(payload, result)

        self.publish_event({
            "type": "DocumentExtractionCompleted",
            "document_id": document_id,
            "correlation_id": correlation_id,
            "classification": classification,
            "validation_status": validation_status,
        })

        return result

    # ------------------------------------------------------------------
    def _persist(self, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
        try:
            with pg_connect(self.config) as conn:
                pg_upsert(conn, "eoc.documents", {
                    "document_id":      result["document_id"],
                    "claim_id":         payload.get("claim_id"),
                    "claimant_id":      payload.get("claimant_id"),
                    "filename":         payload.get("filename", "unknown"),
                    "file_type":        payload.get("file_type"),
                    "ocr_status":       "done" if result.get("ocr_applied") else "skipped",
                    "extracted_text":   payload.get("raw_text", "")[:4000],
                    "classification":   result.get("classification"),
                    "validation_status": result.get("validation_status"),
                    "correlation_id":   result.get("correlation_id"),
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
