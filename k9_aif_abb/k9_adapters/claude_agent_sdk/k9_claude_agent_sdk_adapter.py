# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Primary K9-AIF facade for Claude Agent SDK integration.

Structurally parallel to K9CrewAIAdapter, with one deliberate difference:
where K9CrewAIAdapter is constructed around a caller-supplied ``crew``
object (CrewAI has no equivalent broker requirement -- the crew already
owns its own agents/tools before the adapter ever sees it),
K9ClaudeAgentSDKAdapter is constructed around a caller-supplied list of
``ToolCapability`` definitions instead. There is no pre-built "session"
object to accept -- accepting one would mean trusting whatever tools were
already wired into it, which is exactly the encapsulation gap this
package exists to close. See claude_agent_sdk_orchestrator_adapter.py's
module docstring for the full rationale.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .claude_agent_sdk_orchestrator_adapter import (
    ClaudeAgentSDKOrchestratorAdapter,
    ToolCapability,
)
from .claude_agent_sdk_payload_mapper import ClaudeAgentSDKPayloadMapper


class K9ClaudeAgentSDKAdapter:
    """
    OOB facade for integrating a Claude Agent SDK session into K9-AIF.

    Responsibilities:
    - accept K9-AIF-style payloads
    - normalize payloads for the Claude Agent SDK
    - invoke the wrapped SDK session via the orchestrator adapter
    - normalize the SDK's message stream back to K9-AIF format
    """

    def __init__(
        self,
        capabilities: List[ToolCapability],
        subagents: Optional[Dict[str, Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        permission_mode: Optional[str] = None,
        mapper: Optional[ClaudeAgentSDKPayloadMapper] = None,
        orchestrator_adapter: Optional[ClaudeAgentSDKOrchestratorAdapter] = None,
    ) -> None:
        self.mapper = mapper or ClaudeAgentSDKPayloadMapper()
        self.orchestrator_adapter = orchestrator_adapter or ClaudeAgentSDKOrchestratorAdapter(
            capabilities=capabilities,
            subagents=subagents,
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
        )

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Main adapter entrypoint for K9-AIF callers (synchronous contexts)."""
        sdk_input = self.mapper.to_sdk_input(payload)
        result = self.orchestrator_adapter.execute_flow(sdk_input)
        return self.mapper.from_sdk_output(result["messages"])

    async def execute_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Async twin of execute() for callers already inside an event loop."""
        sdk_input = self.mapper.to_sdk_input(payload)
        result = await self.orchestrator_adapter.execute_flow_async(sdk_input)
        return self.mapper.from_sdk_output(result["messages"])
