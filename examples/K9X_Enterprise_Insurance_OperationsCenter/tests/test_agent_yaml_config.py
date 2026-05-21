# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — tests/test_agent_yaml_config.py (SBB)
#
# Proves that K9X agents receive their per-agent YAML config (role, model,
# instructions, routing, …) — not just the global config.yaml — at
# construction time via AgentLoader.

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.agent_loader import AgentLoader

# ---------------------------------------------------------------------------
# Controlled YAML fixtures — values differ from real YAML defaults so that
# test assertions can only pass if the YAML was actually loaded.
# ---------------------------------------------------------------------------

CLAIMS_TRIAGE_YAML = {
    "name": "ClaimsTriageAgent",
    "class": "ClaimsTriageAgent",
    "description": "Test claims triage",
    "pattern": "reasoning",
    "model": "fast",          # real YAML uses "reasoning" — "fast" proves we control it
    "role": "Test triage role override.",
    "goal": "Test triage goal.",
    "instructions": ["check completeness", "score priority"],
    "config": {"confidence_threshold": 0.9},
    "routing": {"next_on_success": "AdjudicationAgent"},
    "governance": {"pre_process": True, "post_process": False},
}

FRAUD_DETECTION_YAML = {
    "name": "FraudDetectionAgent",
    "class": "FraudDetectionAgent",
    "description": "Test fraud detection",
    "pattern": "reasoning",
    "model": "review",        # real YAML uses "reasoning"
    "role": "Test fraud detection role.",
    "goal": "Test fraud goal.",
    "instructions": ["rule check", "llm correlation"],
    "escalation": {"auto_escalate_threshold": 0.95},
}


@pytest.fixture
def agent_yaml_dir(tmp_path: Path) -> Path:
    (tmp_path / "claims_triage_agent.yaml").write_text(
        yaml.safe_dump(CLAIMS_TRIAGE_YAML), encoding="utf-8"
    )
    (tmp_path / "fraud_detection_agent.yaml").write_text(
        yaml.safe_dump(FRAUD_DETECTION_YAML), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def real_agents_yaml_dir() -> Path:
    """Path to the real agents/yaml directory in the EOC SBB."""
    return Path(__file__).resolve().parents[1] / "agents" / "yaml"


# ---------------------------------------------------------------------------
# AgentLoader unit tests
# ---------------------------------------------------------------------------

class TestAgentLoader:
    def test_indexes_by_class(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        assert loader.has_agent("ClaimsTriageAgent")
        assert loader.has_agent("FraudDetectionAgent")
        assert not loader.has_agent("NonExistentAgent")

    def test_list_classes(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        assert set(loader.list_classes()) == {"ClaimsTriageAgent", "FraudDetectionAgent"}

    def test_get_agent_yaml_returns_fields(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        cfg = loader.get_agent_yaml("ClaimsTriageAgent")
        assert cfg["role"] == "Test triage role override."
        assert cfg["model"] == "fast"
        assert cfg["pattern"] == "reasoning"
        assert cfg["instructions"] == ["check completeness", "score priority"]

    def test_merge_preserves_global_infrastructure_keys(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        global_cfg = {
            "inference": {"llm_factory": {"models": {"general": {}}}},
            "messaging": {"brokers": ["kafka:9092"]},
            "eoc": {"confidence_gate": 0.75},
        }
        merged = loader.merge_with_global("ClaimsTriageAgent", global_cfg)
        assert "inference" in merged
        assert "messaging" in merged
        assert "eoc" in merged

    def test_agent_yaml_wins_on_key_collision(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        merged = loader.merge_with_global("ClaimsTriageAgent", {"model": "global_fallback"})
        assert merged["model"] == "fast"   # YAML wins

    def test_unknown_class_returns_global_unchanged(self, agent_yaml_dir):
        loader = AgentLoader(agent_yaml_dir)
        global_cfg = {"app": {"name": "test"}}
        assert loader.merge_with_global("GhostAgent", global_cfg) == global_cfg

    def test_missing_dir_produces_empty_loader(self, tmp_path):
        loader = AgentLoader(tmp_path / "does_not_exist")
        assert loader.list_classes() == []

    def test_real_agents_yaml_dir_has_all_eoc_agents(self, real_agents_yaml_dir):
        """Sanity-check: real agents/yaml/ directory contains all expected classes."""
        loader = AgentLoader(real_agents_yaml_dir)
        expected = {
            "ClaimsTriageAgent",
            "AdjudicationAgent",
            "GuardAgent",
            "AuditAgent",
            "EscalationAgent",
            "FraudDetectionAgent",
            "DocumentExtractorAgent",
            "GraphSyncAgent",
        }
        assert expected.issubset(set(loader.list_classes()))


# ---------------------------------------------------------------------------
# Integration: K9X agents receive YAML config via AgentLoader
#
# K9X agents catch router init exceptions, so no mocking needed.
# The agent will have _router=None but self.config will contain the merged dict.
# ---------------------------------------------------------------------------

class TestAgentReceivesYamlConfig:
    def test_claims_triage_agent_config_has_yaml_role(self, agent_yaml_dir):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
            ClaimsTriageAgent,
        )
        loader = AgentLoader(agent_yaml_dir)
        agent = ClaimsTriageAgent(config=loader.merge_with_global("ClaimsTriageAgent", {}))

        assert agent.config.get("role") == "Test triage role override."

    def test_claims_triage_agent_config_has_yaml_model(self, agent_yaml_dir):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
            ClaimsTriageAgent,
        )
        loader = AgentLoader(agent_yaml_dir)
        agent = ClaimsTriageAgent(config=loader.merge_with_global("ClaimsTriageAgent", {}))

        assert agent.config.get("model") == "fast"

    def test_claims_triage_agent_config_has_yaml_instructions(self, agent_yaml_dir):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
            ClaimsTriageAgent,
        )
        loader = AgentLoader(agent_yaml_dir)
        agent = ClaimsTriageAgent(config=loader.merge_with_global("ClaimsTriageAgent", {}))

        assert agent.config.get("instructions") == ["check completeness", "score priority"]

    def test_claims_triage_agent_config_has_routing(self, agent_yaml_dir):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
            ClaimsTriageAgent,
        )
        loader = AgentLoader(agent_yaml_dir)
        agent = ClaimsTriageAgent(config=loader.merge_with_global("ClaimsTriageAgent", {}))

        assert agent.config.get("routing", {}).get("next_on_success") == "AdjudicationAgent"

    def test_fraud_detection_agent_config_has_yaml_role(self, agent_yaml_dir):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.fraud_detection_agent import (
            FraudDetectionAgent,
        )
        loader = AgentLoader(agent_yaml_dir)
        agent = FraudDetectionAgent(config=loader.merge_with_global("FraudDetectionAgent", {}))

        assert agent.config.get("role") == "Test fraud detection role."
        assert agent.config.get("model") == "review"

    def test_global_config_keys_reach_agent(self, agent_yaml_dir):
        """Infrastructure keys from global config must survive the merge."""
        from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
            ClaimsTriageAgent,
        )
        global_cfg = {
            "eoc": {"confidence_gate": 0.75},
            "messaging": {"brokers": ["kafka:9092"]},
        }
        loader = AgentLoader(agent_yaml_dir)
        agent = ClaimsTriageAgent(config=loader.merge_with_global("ClaimsTriageAgent", global_cfg))

        assert agent.config.get("eoc", {}).get("confidence_gate") == 0.75
        assert "messaging" in agent.config


# ---------------------------------------------------------------------------
# Key proof: changing YAML changes agent config without touching Python code
# ---------------------------------------------------------------------------

def test_changing_yaml_role_changes_agent_config_role(tmp_path):
    """Editing role in YAML changes agent.config['role'] — no Python code edit needed."""
    from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
        ClaimsTriageAgent,
    )

    yaml_v1 = dict(CLAIMS_TRIAGE_YAML, role="Version one role")
    (tmp_path / "claims_triage_agent.yaml").write_text(yaml.safe_dump(yaml_v1))
    agent_v1 = ClaimsTriageAgent(
        config=AgentLoader(tmp_path).merge_with_global("ClaimsTriageAgent", {})
    )
    assert agent_v1.config.get("role") == "Version one role"

    yaml_v2 = dict(CLAIMS_TRIAGE_YAML, role="Version two role")
    (tmp_path / "claims_triage_agent.yaml").write_text(yaml.safe_dump(yaml_v2))
    agent_v2 = ClaimsTriageAgent(
        config=AgentLoader(tmp_path).merge_with_global("ClaimsTriageAgent", {})
    )
    assert agent_v2.config.get("role") == "Version two role"

    assert agent_v1.config.get("role") != agent_v2.config.get("role")


def test_changing_yaml_model_changes_agent_config_model(tmp_path):
    """Editing model in YAML changes agent.config['model'] — no Python code edit needed."""
    from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import (
        ClaimsTriageAgent,
    )

    for model_alias in ("fast", "reasoning", "review"):
        yaml_data = dict(CLAIMS_TRIAGE_YAML, model=model_alias)
        (tmp_path / "claims_triage_agent.yaml").write_text(yaml.safe_dump(yaml_data))
        agent = ClaimsTriageAgent(
            config=AgentLoader(tmp_path).merge_with_global("ClaimsTriageAgent", {})
        )
        assert agent.config.get("model") == model_alias
