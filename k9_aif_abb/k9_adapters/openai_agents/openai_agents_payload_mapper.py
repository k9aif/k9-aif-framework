# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Payload mapping between K9-AIF payloads and the OpenAI Agents SDK.

Input side: the same flexible conventions as the CrewAI and Claude mappers
(``message`` / ``input`` / ``query``). Output side: a ``RunResult`` becomes the K9-AIF
envelope ``{"status", "result", "output_text"}``. Called once, at the facade.
"""

from __future__ import annotations

from typing import Any, Dict


class OpenAIAgentsPayloadMapper:
    """Translate K9-AIF payloads to Runner input, and a RunResult back."""

    def to_sdk_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = payload or {}
        prompt = payload.get("message") or payload.get("input") or payload.get("query") or ""
        mapped = {k: v for k, v in payload.items() if k not in ("message", "input", "query")}
        mapped["prompt"] = prompt
        return mapped

    def from_sdk_output(self, result: Any) -> Dict[str, Any]:
        """``result`` is the adapter's ``{"run_result": RunResult, "trace": [...]}``."""
        run = result["run_result"]
        final = run.final_output
        output_text = final if isinstance(final, str) else repr(final)
        items = [{"type": getattr(i, "type", type(i).__name__),
                  "agent": getattr(getattr(i, "agent", None), "name", None)} for i in run.new_items]
        return {
            "status": "success",
            "result": {
                "last_agent": getattr(run.last_agent, "name", None),
                "items": items,
                "model_calls": len(run.raw_responses),
                "governance_trace": result.get("trace", []),
            },
            "output_text": output_text.strip() if isinstance(output_text, str) else output_text,
        }
