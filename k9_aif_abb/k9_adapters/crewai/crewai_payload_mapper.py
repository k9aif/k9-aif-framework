# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Payload mapping utilities for adapting K9-AIF payloads to CrewAI-friendly inputs.
"""

from __future__ import annotations

from typing import Any, Dict


class CrewAIPayloadMapper:
    """Translate K9-AIF payloads into normalized CrewAI inputs."""

    def to_crewai_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize incoming K9-AIF payload into a structure suitable for CrewAI.

        Expected flexible input examples:
        - {"message": "...", "intent": "support"}
        - {"input": "..."}
        - {"query": "...", "context": {...}}
        """
        payload = payload or {}

        message = (
            payload.get("message")
            or payload.get("input")
            or payload.get("query")
            or ""
        )

        return {
            "message": message,
            "intent": payload.get("intent"),
            "context": payload.get("context", {}),
            "metadata": payload.get("metadata", {}),
            "raw_payload": payload,
        }

    def from_crewai_output(self, result: Any) -> Dict[str, Any]:
        """
        Normalize CrewAI output back into a K9-AIF-friendly response envelope.

        A real ``crew.kickoff()`` returns a ``CrewOutput`` (a Pydantic
        model), not a plain dict -- only exercised for the first time once
        this adapter was actually run against live CrewAI/Ollama rather
        than the test suite's dict-returning DummyCrew. Storing that raw
        object under "result" is not JSON-serializable, so any caller
        (this adapter's own webui.py included) crashes trying to return
        it. ``model_dump()`` (Pydantic v2) is checked first and is the
        general fix for any Pydantic-model result, not just CrewOutput
        specifically -- this mapper has no CrewAI import and should not
        need one just to serialize its output.
        """
        if isinstance(result, dict):
            return {
                "status": "success",
                "result": result,
                "output_text": result.get("output") or result.get("message") or str(result),
            }

        if hasattr(result, "model_dump"):
            return {
                "status": "success",
                "result": result.model_dump(mode="json"),
                "output_text": getattr(result, "raw", None) or str(result),
            }

        return {
            "status": "success",
            "result": str(result),
            "output_text": str(result),
        }