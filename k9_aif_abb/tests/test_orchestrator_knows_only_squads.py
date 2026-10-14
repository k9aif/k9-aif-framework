# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""The orchestrator knows only squads (1.18.1).

The agents a squad needs are named in its own YAML and built by the squad layer
(SquadLoader.from_agents). The acceptance test: change a squad's agents and the
orchestrator, unchanged, still runs it.
"""

import sys
import textwrap

import pytest

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_inspect import InspectionRuleRegistry
from k9_aif_abb.k9_inspect.project import SolutionProject
from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_squad.squad_loader import SquadLoader


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))
    return p


AGENT_SRC = '''
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent

class {name}(BaseAgent):
    def execute(self, payload):
        seen = sorted(k for k in payload if k.startswith("r_"))
        return {{"output": "{name}", "seen": seen, "tone": self.config.get("tone")}}
'''


def add_agent(root, pkg, name):
    write(root, f"{pkg}/{name.lower()}.py", AGENT_SRC.format(name=name))
    write(root, f"agents/{name.lower()}.yaml", f"""
        class: {name}
        module: {pkg}.{name.lower()}
        role: test agent
    """)


def squad_yaml(root, agents):
    flow = "".join(f"\n          - agent: {a}\n            result_key: r_{a.lower()}" for a in agents)
    names = "".join(f"\n          - {a}" for a in agents)
    write(root, "squads/review_squad.yaml",
          "squads:\n  ReviewSquad:\n    agents:" + names.replace("\n          ", "\n      ")
          + "\n    flow:" + flow.replace("\n          ", "\n      ").replace("\n            ", "\n        "))


class ReviewOrchestrator(BaseOrchestrator):
    """Names one squad, nothing else."""

    def __init__(self, squads_dir, **kw):
        super().__init__(**kw)
        self.squads_dir = squads_dir

    def execute_flow(self, payload):
        return self.squads.load_one(self.squads_dir / "review_squad.yaml", "ReviewSquad").execute(payload)


@pytest.fixture
def app(tmp_path, monkeypatch):
    pkg = f"sqapp_{tmp_path.name.replace('-', '_')}"
    (tmp_path / pkg).mkdir()
    (tmp_path / pkg / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path, pkg
    for m in [m for m in sys.modules if m.startswith(pkg)]:
        del sys.modules[m]


def test_squad_agents_change_orchestrator_unaffected(app):
    root, pkg = app
    add_agent(root, pkg, "DraftAgent")
    squad_yaml(root, ["DraftAgent"])
    squads = SquadLoader.from_agents(root / "agents", config={"tone": "plain"})
    orch = ReviewOrchestrator(root / "squads", config={}, squads=squads)

    first = orch.execute_flow({"job_id": "j1"})
    assert list(k for k in first if k.startswith("r_")) == ["r_draftagent"]

    # The squad gains an agent: only the squad YAML and the new agent change.
    add_agent(root, pkg, "CheckAgent")
    squad_yaml(root, ["DraftAgent", "CheckAgent"])

    second = orch.execute_flow({"job_id": "j2"})
    assert second["r_checkagent"]["output"] == "CheckAgent"
    assert second["r_checkagent"]["seen"] == ["r_draftagent"]      # context enrichment intact
    assert second["r_draftagent"]["tone"] == "plain"                # agent YAML merged with global config


def test_per_load_config_reaches_the_agents(app):
    root, pkg = app
    add_agent(root, pkg, "DraftAgent")
    squad_yaml(root, ["DraftAgent"])
    squads = SquadLoader.from_agents(root / "agents", config={"tone": "plain"})
    squad = squads.load_one(root / "squads" / "review_squad.yaml", "ReviewSquad", config={"tone": "override"})
    assert squad.execute({})["r_draftagent"]["tone"] == "override"


def test_squad_class_and_before_step(app):
    root, pkg = app
    add_agent(root, pkg, "DraftAgent")
    add_agent(root, pkg, "CheckAgent")
    squad_yaml(root, ["DraftAgent", "CheckAgent"])

    class StoppableSquad(BaseSquad):
        calls = []

        def before_step(self, agent_name, context):
            self.calls.append(agent_name)
            if context.get("stop_before") == agent_name:
                raise RuntimeError(f"stopped before {agent_name}")

    squads = SquadLoader.from_agents(root / "agents", squad_cls=StoppableSquad)
    squad = squads.load_one(root / "squads" / "review_squad.yaml", "ReviewSquad")
    assert isinstance(squad, StoppableSquad)
    squad.execute({})
    assert StoppableSquad.calls == ["DraftAgent", "CheckAgent"]
    with pytest.raises(RuntimeError, match="stopped before CheckAgent"):
        squad.execute({"stop_before": "CheckAgent"})


def test_loader_needs_an_agent_source():
    with pytest.raises(ValueError):
        SquadLoader()


def _dec002(root):
    rule = InspectionRuleRegistry.get("K9-DEC-002")() if hasattr(InspectionRuleRegistry, "get") else None
    if rule is None:
        from k9_aif_abb.k9_inspect.rules.code_rules import OrchestratorKnowsOnlySquadsRule
        rule = OrchestratorKnowsOnlySquadsRule()
    return rule.inspect(SolutionProject(root))


def test_inspector_flags_orchestrator_that_names_or_builds_agents(tmp_path):
    write(tmp_path, "agents/draft_agent.py", """
        from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
        class DraftAgent(BaseAgent):
            def execute(self, payload):
                return {}
    """)
    write(tmp_path, "orchestrators/bad_orchestrator.py", """
        from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
        from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
        class BadOrchestrator(BaseOrchestrator):
            AGENTS = ("DraftAgent",)
            def execute_flow(self, payload):
                registry = AgentRegistry()
                return {}
    """)
    write(tmp_path, "orchestrators/good_orchestrator.py", """
        from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
        class GoodOrchestrator(BaseOrchestrator):
            def execute_flow(self, payload):
                return self.squads.load_one("squads/review_squad.yaml", "ReviewSquad").execute(payload)
    """)
    findings = _dec002(tmp_path)
    assert {f.file for f in findings} == {"orchestrators/bad_orchestrator.py"}
    messages = " | ".join(f.message for f in findings)
    assert "AgentRegistry" in messages and "DraftAgent" in messages
