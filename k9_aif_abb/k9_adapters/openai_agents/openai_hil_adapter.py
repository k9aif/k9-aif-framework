# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
OpenAIHILAdapter (1.29.0): the OpenAI Agents SDK's human-in-the-loop, routed through K9X HIL.

The SDK pauses a run when a tool marked ``needs_approval`` is called: ``result.interruptions`` lists the waiting
calls, ``result.to_state().to_string()`` saves the run, ``RunState.from_string(agent, saved)`` restores it, and
``approve()`` / ``reject()`` record the decision before ``Runner.run(agent, state)`` continues where it stopped.
The SDK has no task queue, sign-in, roles, deadlines or audit trail. This adapter maps its pause to a K9X HIL
request and the K9X HIL reply back to approve / reject (see ``BaseHILAdapter``).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from agents import Agent, RunState

from k9_aif_abb.k9_core.orchestration.base_hil_adapter import BaseHILAdapter, HILDecision


class OpenAIHILAdapter(BaseHILAdapter):
    framework = "openai_agents"

    def describe_pause(self, pause: Any) -> Dict[str, Any]:
        return {"tool_calls": [{"tool": item.tool_name, "arguments": _arguments(item)}
                               for item in pause.interruptions]}

    def serialize_pause(self, pause: Any) -> str:
        return pause.to_state().to_string()

    async def restore(self, agent: Agent, saved: Dict[str, Any], decision: HILDecision) -> RunState:
        """The paused run, restored, with the person's decision applied to every waiting call."""
        state = await RunState.from_string(agent, saved["state"])
        for item in state.get_interruptions():
            if decision.approved:
                state.approve(item)
            else:
                state.reject(item, rejection_message=decision.rejection_message())
        return state


def _arguments(item: Any) -> Any:
    raw = getattr(item, "raw_item", None)
    args = getattr(raw, "arguments", None) if raw is not None else None
    if args is None and isinstance(raw, dict):
        args = raw.get("arguments")
    try:
        return json.loads(args) if isinstance(args, str) else args
    except ValueError:
        return args
