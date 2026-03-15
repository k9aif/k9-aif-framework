# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary

from pathlib import Path

import pytest
import yaml

from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_squad.squad_loader import SquadLoader


class DummyAgentA:
    def execute(self, context):
        return context


class DummyAgentB:
    def execute(self, context):
        return context


class DummyOrchestrator:
    def execute(self, squad, context):
        return context


class DummyAgentRegistry:
    def __init__(self):
        self._registry = {
            "DummyAgentA": DummyAgentA,
            "DummyAgentB": DummyAgentB,
        }

    def create(self, name):
        if name not in self._registry:
            raise KeyError(f"Agent '{name}' not registered")
        return self._registry[name]()


class DummyOrchestratorRegistry:
    def __init__(self):
        self._registry = {
            "dummy": DummyOrchestrator,
        }

    def create(self, name):
        if name not in self._registry:
            raise KeyError(f"Orchestrator '{name}' not registered")
        return self._registry[name]()


def write_yaml(tmp_path: Path, content: dict) -> Path:
    path = tmp_path / "example_squads.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return path


def test_load_single_squad(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "claims_intake": {
                    "description": "Test squad",
                    "orchestrator": "dummy",
                    "agents": ["DummyAgentA", "DummyAgentB"],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    squads = loader.load(yaml_path)

    assert "claims_intake" in squads

    squad = squads["claims_intake"]
    assert isinstance(squad, BaseSquad)
    assert squad.squad_id == "claims_intake"
    assert len(squad.agents) == 2
    assert isinstance(squad.agents[0], DummyAgentA)
    assert isinstance(squad.agents[1], DummyAgentB)
    assert isinstance(squad.orchestrator, DummyOrchestrator)
    assert squad.description == "Test squad"


def test_load_multiple_squads(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "squad_one": {
                    "orchestrator": "dummy",
                    "agents": ["DummyAgentA"],
                },
                "squad_two": {
                    "orchestrator": "dummy",
                    "agents": ["DummyAgentB"],
                },
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    squads = loader.load(yaml_path)

    assert set(squads.keys()) == {"squad_one", "squad_two"}
    assert len(squads["squad_one"].agents) == 1
    assert len(squads["squad_two"].agents) == 1


def test_load_one_squad_by_id(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "claims_intake": {
                    "orchestrator": "dummy",
                    "agents": ["DummyAgentA"],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    squad = loader.load_one(yaml_path, "claims_intake")

    assert squad.squad_id == "claims_intake"
    assert len(squad.agents) == 1
    assert isinstance(squad.agents[0], DummyAgentA)


def test_missing_squads_section_raises_error(tmp_path):
    yaml_path = write_yaml(tmp_path, {"not_squads": {}})

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    with pytest.raises(ValueError, match="No 'squads' section found"):
        loader.load(yaml_path)


def test_missing_orchestrator_raises_error(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "bad_squad": {
                    "agents": ["DummyAgentA"],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    with pytest.raises(ValueError, match="missing required field: 'orchestrator'"):
        loader.load(yaml_path)


def test_missing_agents_raises_error(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "bad_squad": {
                    "orchestrator": "dummy",
                    "agents": [],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    with pytest.raises(ValueError, match="must define at least one agent"):
        loader.load(yaml_path)


def test_unknown_agent_raises_error(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "bad_squad": {
                    "orchestrator": "dummy",
                    "agents": ["UnknownAgent"],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    with pytest.raises(ValueError, match="Failed to create agent 'UnknownAgent'"):
        loader.load(yaml_path)


def test_unknown_orchestrator_raises_error(tmp_path):
    yaml_path = write_yaml(
        tmp_path,
        {
            "squads": {
                "bad_squad": {
                    "orchestrator": "unknown",
                    "agents": ["DummyAgentA"],
                }
            }
        },
    )

    loader = SquadLoader(
        agent_registry=DummyAgentRegistry(),
        orchestrator_registry=DummyOrchestratorRegistry(),
    )

    with pytest.raises(KeyError, match="Orchestrator 'unknown' not registered"):
        loader.load(yaml_path)