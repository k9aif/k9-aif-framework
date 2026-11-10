# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ToolCall: one tool call an agent proposes, as the framework intercepted it.

The framework builds it from the call itself (tool name, exact arguments) and
from the governed request it runs in (request id, agent). The agent's own
explanation, if it gives one, is kept apart in ``rationale_untrusted``: a
reviewer may read it, but nothing decides on it.

``digest()`` fingerprints the tool name and arguments, so an approval can be
tied to exactly the call that was reviewed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    request_id: Optional[str] = None
    agent_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rationale_untrusted: Optional[str] = None

    def digest(self) -> str:
        """sha256 over the tool name and its arguments (canonical JSON)."""
        body = _canonical({"tool": self.tool_name, "arguments": self.arguments})
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "correlation_id": self.correlation_id,
            "rationale_untrusted": self.rationale_untrusted,
            "digest": self.digest(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(
            tool_name=data["tool_name"],
            arguments=dict(data.get("arguments") or {}),
            request_id=data.get("request_id"),
            agent_id=data.get("agent_id"),
            correlation_id=data["correlation_id"],
            rationale_untrusted=data.get("rationale_untrusted"),
        )
