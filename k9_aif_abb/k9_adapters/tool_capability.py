# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ToolCapability: one tool an agent-runtime adapter is willing to broker (1.27.0).

Shared by the Claude Agent SDK and OpenAI Agents SDK adapters. Before 1.27.0 it lived in
``claude_agent_sdk_orchestrator_adapter``, which still re-exports it, so existing imports
keep working.

The adapter, not the caller, turns each capability into the runtime's own tool type. A
runtime never receives a tool object the caller built, so every tool it can call is one
the adapter registered and governs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict


@dataclass(frozen=True)
class ToolCapability:
    """One capability an adapter brokers to the agent runtime it wraps.

    ``handler`` is ``async def handler(args: dict) -> Any``. ``input_schema`` is a JSON
    Schema object for the arguments; the Claude adapter also accepts the SDK's
    ``{"name": type}`` shorthand.
    """

    name: str
    description: str
    input_schema: Any
    handler: Callable[[Dict[str, Any]], Awaitable[Any]]
