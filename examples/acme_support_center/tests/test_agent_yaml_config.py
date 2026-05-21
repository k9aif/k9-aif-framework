# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — acme_support_center SBB
#
# Proves that agents receive their per-agent YAML config (role, model,
# instructions, …) — not just the global config.yaml — at construction time.

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from examples.acme_support_center.utils.agent_loader import AgentLoader

# ---------------------------------------------------------------------------
# Fixture YAML data mirrors the real agents/yaml/ files but uses controlled
# values so the assertions can't accidentally pass against defaults.
# ---------------------------------------------------------------------------

KNOWLEDGE_YAML = {
    "name": "knowledge_agent",
    "class": "KnowledgeAgent",
    "description": "Test knowledge agent",
    "pattern": "agentic_rag",
    "model": "reasoning",          # non-default → proves YAML is read
    "role": "You are a test knowledge specialist.",
    "goal": "Retrieve and ground every answer.",
    "instructions": ["retrieve first", "cite sources", "no hallucination"],
    "config": {"top_k": 7, "rerank": True},
}

TRIAGE_YAML = {
    "name": "triage_agent",
    "class": "TriageAgent",
    "description": "Test triage agent",
    "pattern": "react",
    "model": "fast",
    "role": "You are a test triage specialist.",
    "goal": "Classify and route.",
    "instructions": ["read", "classify", "route"],
    "config": {"max_iterations": 9},
    "routing": {"account_help": "resolution_agent"},
}


@pytest.fixture
def agent_yaml_dir(tmp_path: Path) -> Path:
    (tmp_path / "knowledge_agent.yaml").write_text(
        yaml.safe_dump(KNOWLEDGE_YAML), encoding="utf-8"
    )
    (tmp_path / "triage_agent.yaml").write_text(
        yaml.safe_dump(TRIAGE_YAML), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# AgentLoader unit tests
# ---------------------------------------------------------------------------

class TestAgentLoader:
    def test_indexes_by_class(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        assert loader.has_agent("KnowledgeAgent")
        assert loader.has_agent("TriageAgent")
        assert not loader.has_agent("GhostAgent")

    def test_list_classes(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        assert set(loader.list_classes()) == {"KnowledgeAgent", "TriageAgent"}

    def test_get_agent_yaml_returns_fields(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        cfg = loader.get_agent_yaml("KnowledgeAgent")
        assert cfg["role"] == "You are a test knowledge specialist."
        assert cfg["model"] == "reasoning"
        assert cfg["pattern"] == "agentic_rag"
        assert cfg["instructions"] == ["retrieve first", "cite sources", "no hallucination"]
        assert cfg["config"]["top_k"] == 7

    def test_merge_preserves_global_infrastructure(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        global_cfg = {
            "inference": {"llm_factory": {"models": {"general": {}}}},
            "runtime": {"environment": "test"},
        }
        merged = loader.merge_with_global("KnowledgeAgent", global_cfg)
        assert "inference" in merged
        assert "runtime" in merged
        assert merged["role"] == "You are a test knowledge specialist."

    def test_agent_yaml_wins_on_key_collision(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        merged = loader.merge_with_global("KnowledgeAgent", {"model": "global_default"})
        assert merged["model"] == "reasoning"   # YAML wins

    def test_unknown_class_returns_global_unchanged(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        global_cfg = {"app": {"name": "test"}}
        merged = loader.merge_with_global("NonExistentAgent", global_cfg)
        assert merged == global_cfg

    def test_missing_dir_produces_empty_loader(self, tmp_path):
        loader = AgentLoader(tmp_path / "does_not_exist")
        assert loader.list_classes() == []


# ---------------------------------------------------------------------------
# Integration: KnowledgeAgent receives YAML config
# ---------------------------------------------------------------------------

_MOCK_ROUTER_PATH = (
    "examples.acme_support_center.agents.src.acme_base_agent.ModelRouterFactory.get_router"
)


@patch(_MOCK_ROUTER_PATH)
def test_knowledge_agent_role_comes_from_yaml(mock_router, agent_yaml_dir):
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    loader = AgentLoader(agent_yaml_dir)
    agent = KnowledgeAgent(config=loader.merge_with_global("KnowledgeAgent", {}))

    assert agent.role == "You are a test knowledge specialist."


@patch(_MOCK_ROUTER_PATH)
def test_knowledge_agent_model_comes_from_yaml(mock_router, agent_yaml_dir):
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    loader = AgentLoader(agent_yaml_dir)
    agent = KnowledgeAgent(config=loader.merge_with_global("KnowledgeAgent", {}))

    assert agent.model == "reasoning"


@patch(_MOCK_ROUTER_PATH)
def test_knowledge_agent_instructions_come_from_yaml(mock_router, agent_yaml_dir):
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    loader = AgentLoader(agent_yaml_dir)
    agent = KnowledgeAgent(config=loader.merge_with_global("KnowledgeAgent", {}))

    assert agent.instructions == ["retrieve first", "cite sources", "no hallucination"]
    assert agent.agent_config.get("top_k") == 7
    assert agent.agent_config.get("rerank") is True


@patch(_MOCK_ROUTER_PATH)
def test_knowledge_agent_pattern_comes_from_yaml(mock_router, agent_yaml_dir):
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    loader = AgentLoader(agent_yaml_dir)
    agent = KnowledgeAgent(config=loader.merge_with_global("KnowledgeAgent", {}))

    assert agent.pattern == "agentic_rag"
    assert agent.goal == "Retrieve and ground every answer."


@patch(_MOCK_ROUTER_PATH)
def test_changing_yaml_role_changes_agent_role(mock_router, tmp_path):
    """Prove YAML drives config: editing role in YAML changes agent.role."""
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    yaml_v1 = dict(KNOWLEDGE_YAML, role="Role alpha")
    (tmp_path / "knowledge_agent.yaml").write_text(yaml.safe_dump(yaml_v1))
    agent_v1 = KnowledgeAgent(
        config=AgentLoader(tmp_path).merge_with_global("KnowledgeAgent", {})
    )
    assert agent_v1.role == "Role alpha"

    yaml_v2 = dict(KNOWLEDGE_YAML, role="Role beta")
    (tmp_path / "knowledge_agent.yaml").write_text(yaml.safe_dump(yaml_v2))
    agent_v2 = KnowledgeAgent(
        config=AgentLoader(tmp_path).merge_with_global("KnowledgeAgent", {})
    )
    assert agent_v2.role == "Role beta"

    assert agent_v1.role != agent_v2.role


@patch(_MOCK_ROUTER_PATH)
def test_changing_yaml_model_changes_agent_model(mock_router, tmp_path):
    """Prove that changing model in YAML changes agent.model without code edits."""
    mock_router.return_value = MagicMock()
    from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent

    for model_alias in ("fast", "reasoning", "review"):
        yaml_data = dict(KNOWLEDGE_YAML, model=model_alias)
        (tmp_path / "knowledge_agent.yaml").write_text(yaml.safe_dump(yaml_data))
        agent = KnowledgeAgent(
            config=AgentLoader(tmp_path).merge_with_global("KnowledgeAgent", {})
        )
        assert agent.model == model_alias
