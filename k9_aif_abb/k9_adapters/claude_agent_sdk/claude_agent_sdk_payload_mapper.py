# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Payload mapping utilities for adapting K9-AIF payloads to Claude Agent SDK
inputs, and SDK message streams back to K9-AIF response envelopes.

Structurally parallel to CrewAIPayloadMapper, but the output side is not a
parallel: CrewAI's crew.kickoff() returns one object. The Claude Agent SDK's
query() yields a *stream* of typed messages (UserMessage, AssistantMessage,
SystemMessage, ResultMessage, ...) as the agent loop progresses turn by
turn. from_sdk_output() consumes that stream, not a single return value.
"""

from __future__ import annotations

from typing import Any, Dict, List


class ClaudeAgentSDKPayloadMapper:
    """Translate K9-AIF payloads into normalized Claude Agent SDK inputs,
    and normalize the SDK's message stream back into a K9-AIF response."""

    def to_sdk_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize incoming K9-AIF payload into the shape the orchestrator
        adapter needs to build a query() call.

        Expected flexible input examples (same conventions as
        CrewAIPayloadMapper, for symmetry at the K9-AIF-facing boundary):
        - {"message": "...", "intent": "support"}
        - {"input": "..."}
        - {"query": "...", "context": {...}}
        """
        payload = payload or {}

        prompt = (
            payload.get("message")
            or payload.get("input")
            or payload.get("query")
            or ""
        )

        return {
            "prompt": prompt,
            "intent": payload.get("intent"),
            "context": payload.get("context", {}),
            "metadata": payload.get("metadata", {}),
            "raw_payload": payload,
        }

    def from_sdk_output(self, messages: List[Any]) -> Dict[str, Any]:
        """
        Normalize a completed Claude Agent SDK message stream into the same
        response envelope shape CrewAIPayloadMapper produces:
        {"status", "result", "output_text"}.

        ``messages`` is the accumulated list of messages yielded by
        query() for one turn sequence (UserMessage / AssistantMessage /
        SystemMessage / ResultMessage / StreamEvent / RateLimitEvent).
        The final assistant text and the terminal ResultMessage (if any)
        are what callers actually care about; intermediate tool-use turns
        are preserved in ``result.transcript`` for audit, not discarded.
        """
        output_text = ""
        result_message = None
        transcript: List[Dict[str, Any]] = []

        for msg in messages:
            type_name = type(msg).__name__
            transcript.append({"type": type_name, "repr": repr(msg)})

            if type_name == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        output_text = text  # last assistant text wins

            if type_name == "ResultMessage":
                result_message = msg

        status = "success"
        if result_message is not None and getattr(result_message, "is_error", False):
            status = "error"

        return {
            "status": status,
            "result": {
                "transcript": transcript,
                "result_message": repr(result_message) if result_message else None,
            },
            "output_text": output_text,
        }
