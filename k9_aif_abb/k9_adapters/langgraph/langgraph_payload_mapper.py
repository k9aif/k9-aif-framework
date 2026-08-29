"""
Payload mapping utilities for adapting K9-AIF payloads to LangGraph-friendly
inputs. Mirrors k9_adapters/crewai/crewai_payload_mapper.py exactly -- same
role, same contract, different wrapped framework.
"""

from __future__ import annotations

from typing import Any, Dict


class LangGraphPayloadMapper:
    """Translate K9-AIF payloads into normalized LangGraph inputs."""

    def to_langgraph_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize incoming K9-AIF payload into a structure suitable for a
        compiled LangGraph's invoke().

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

    def from_langgraph_output(self, result: Any) -> Dict[str, Any]:
        """
        Normalize a compiled LangGraph's final state dict back into a
        K9-AIF-friendly response envelope. This is the only place that
        performs this normalization -- see LangGraphOrchestratorAdapter.
        adapt_output()'s docstring for why that matters.
        """
        if isinstance(result, dict):
            return {
                "status": "success",
                "result": result,
                "output_text": result.get("output")
                or result.get("message")
                or str(result),
            }

        return {
            "status": "success",
            "result": result,
            "output_text": str(result),
        }
