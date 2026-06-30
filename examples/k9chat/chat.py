# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import os
import sys
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from examples.k9chat.chat_agent import ChatAgent

BASE_DIR = os.path.dirname(__file__)
_AGENT = None


def build_chat_agent():
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
        yaml.safe_load(f)

    agent_registry = AgentRegistry()
    agent_registry.register("chat_agent", ChatAgent)

    loader = SquadLoader(agent_registry)
    squads = loader.load(os.path.join(BASE_DIR, "squad.yaml"))

    squad = squads["k9chat"]
    _AGENT = squad.agents[0]
    return _AGENT


def send_message(text: str) -> str:
    agent = build_chat_agent()
    result = agent.execute({"text": text})
    return result.get("text", "")


def is_streaming_enabled() -> bool:
    with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return bool(config.get("chat", {}).get("stream", False))


async def send_message_stream(text: str):
    """Yield response chunks as they arrive — used when chat.stream: true."""
    agent = build_chat_agent()
    async for chunk in agent.execute_stream({"text": text}):
        yield chunk


def get_chat_runtime_info() -> dict:
    with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    inference_cfg = config.get("inference", {})
    llm_factory_cfg = inference_cfg.get("llm_factory", {})
    models = llm_factory_cfg.get("models", {})

    return {
        "provider": llm_factory_cfg.get("provider", "unknown"),
        "base_url": llm_factory_cfg.get("base_url", "unknown"),
        "model": models.get("general", "unknown"),
    }