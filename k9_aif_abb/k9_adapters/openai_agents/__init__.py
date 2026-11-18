# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
OpenAI Agents SDK adapter package for K9-AIF (1.27.0).

Runs OpenAI agents, declared in K9-AIF agent YAML, under K9-AIF governance: Zero Trust and
Shield ingress before the run, Zero Trust for every agent that takes a turn, Shield on every
tool call, tool result and model reply, and the K9 Model Router choosing the model for every
model call. Needs ``pip install "k9-aif[openai-agents]"``.

Two ways to run several agents (1.28.0): ``K9OpenAIAgent`` makes each OpenAI agent an individual
K9-AIF agent that a squad runs in the order its flow sets, with synthesis (the squad decides);
``OpenAIAgentsOrchestratorAdapter`` runs a handoff group (the model decides).
"""

from .k9_openai_agents_adapter import K9OpenAIAgentsAdapter
from .openai_agents_orchestrator_adapter import OpenAIAgentsOrchestratorAdapter, load_agent_specs
from .openai_agents_payload_mapper import OpenAIAgentsPayloadMapper
from .k9_model_provider import K9ModelProvider, K9GovernedModel
from .k9_openai_agent import K9OpenAIAgent
from .openai_hil_adapter import OpenAIHILAdapter
from k9_aif_abb.k9_adapters.tool_capability import ToolCapability

__all__ = [
    "K9OpenAIAgent",
    "OpenAIHILAdapter",
    "K9OpenAIAgentsAdapter",
    "OpenAIAgentsOrchestratorAdapter",
    "OpenAIAgentsPayloadMapper",
    "K9ModelProvider",
    "K9GovernedModel",
    "ToolCapability",
    "load_agent_specs",
]
