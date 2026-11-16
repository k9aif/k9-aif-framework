# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9OpenAIAgentsAdapter: the facade for running OpenAI agents under K9-AIF (1.27.0).

Same three-part shape as the CrewAI, LangGraph and Claude Agent SDK adapters: this facade
accepts a K9-AIF payload, the mapper normalizes it once, the orchestrator adapter governs and
runs the agents, and the mapper turns the run back into a K9-AIF result.

Like the Claude facade, it is built around capabilities and agent specs, never around a
pre-built SDK object.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_adapters.tool_capability import ToolCapability

from .openai_agents_orchestrator_adapter import OpenAIAgentsOrchestratorAdapter, load_agent_specs
from .openai_agents_payload_mapper import OpenAIAgentsPayloadMapper


class K9OpenAIAgentsAdapter:
    """Accept K9-AIF payloads, run governed OpenAI agents, return K9-AIF results."""

    def __init__(
        self,
        capabilities: List[ToolCapability],
        entry_agent: str,
        agents: Optional[Dict[str, Dict[str, Any]]] = None,
        agents_dir: Optional[str | Path] = None,
        mapper: Optional[OpenAIAgentsPayloadMapper] = None,
        orchestrator_adapter: Optional[OpenAIAgentsOrchestratorAdapter] = None,
        **orchestrator_kwargs: Any,
    ) -> None:
        """Give ``agents`` (specs by name) or ``agents_dir`` (a folder of agent YAML).
        ``orchestrator_kwargs`` (config=, governance=, enable_zero_trust=, zero_trust_guard=,
        model_routing=, max_handoffs=, ...) go to the orchestrator adapter."""
        self.mapper = mapper or OpenAIAgentsPayloadMapper()
        if orchestrator_adapter is None:
            if agents is None:
                if agents_dir is None:
                    raise ValueError("[K9OpenAIAgentsAdapter] give agents= or agents_dir=")
                agents = load_agent_specs(agents_dir)
            orchestrator_adapter = OpenAIAgentsOrchestratorAdapter(
                capabilities=capabilities, agents=agents, entry_agent=entry_agent, **orchestrator_kwargs)
        self.orchestrator_adapter = orchestrator_adapter

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Entry point for synchronous callers."""
        return self.mapper.from_sdk_output(self.orchestrator_adapter.execute_flow(self.mapper.to_sdk_input(payload)))

    async def execute_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Entry point for callers already inside an event loop."""
        result = await self.orchestrator_adapter.execute_flow_async(self.mapper.to_sdk_input(payload))
        return self.mapper.from_sdk_output(result)
