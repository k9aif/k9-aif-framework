# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending

from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_squad.squad_context import SquadContext


class DummyAgent:
    def execute(self, context):
        context.set("agent_ran", True)
        return context


class DummyOrchestrator:
    def execute(self, squad, context):
        for agent in squad.agents:
            context = agent.execute(context)
        return context


class DummyMonitor:
    def __init__(self):
        self.started = False
        self.ended = False

    def on_squad_start(self, squad_id):
        self.started = True

    def on_squad_end(self, squad_id):
        self.ended = True


def test_base_squad_run_returns_context():
    squad = BaseSquad(
        squad_id="test_squad",
        agents=[DummyAgent()],
        orchestrator=DummyOrchestrator(),
    )

    result = squad.run({"input": "value"})

    assert isinstance(result, SquadContext)
    assert result.get("input") == "value"
    assert result.get("agent_ran") is True


def test_base_squad_monitor_hooks_are_called():
    monitor = DummyMonitor()

    squad = BaseSquad(
        squad_id="test_squad",
        agents=[DummyAgent()],
        orchestrator=DummyOrchestrator(),
        monitor=monitor,
    )

    squad.run({"input": "value"})

    assert monitor.started is True
    assert monitor.ended is True


def test_base_squad_defaults():
    squad = BaseSquad(
        squad_id="test_squad",
        agents=[],
        orchestrator=DummyOrchestrator(),
    )

    assert squad.squad_id == "test_squad"
    assert squad.agents == []
    assert squad.description == ""
    assert squad.flow == []
    assert squad.metadata == {}