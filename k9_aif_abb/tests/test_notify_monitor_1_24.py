# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
1.24: BaseAgent.notify_monitor() replaces publish_event().

The old name suggested a Kafka publish, but agents are built without a message bus
(K9-KAF-001), so it only ever reached the monitor and the log. notify_monitor() does
exactly that and never touches a bus. publish_event() stays for one release as a
deprecated alias with its old behaviour. Real monitors throughout, no mocks.
"""

import logging
import warnings
from typing import Any, Dict

import pytest

from k9_aif_abb.k9_core.monitoring.base_monitoring import BaseMonitor
from k9_aif_abb.k9_factories.monitor_factory import MonitorFactory
from k9_aif_abb.k9_monitoring.console_monitor import ConsoleMonitor
from k9_aif_abb.tests.test_framework import MinimalAgent, RealGovernance


class _Recording(BaseMonitor):
    def __init__(self):
        super().__init__(name="recording")
        self.seen = []

    def emit_metric(self, name, value, tags=None):
        pass

    def observe(self, event, meta=None):
        self.seen.append((event, meta))


class _Bus:
    """A plain bus that records what is published to it."""

    def __init__(self):
        self.published = []

    def publish(self, event: Dict[str, Any]):
        self.published.append(event)

    def publish_to(self, topic: str, event: Dict[str, Any]):
        self.published.append((topic, event))


class _OtherAgent(MinimalAgent):
    layer = "Other Agent"




def test_notify_monitor_reaches_the_monitor():
    monitor = _Recording()
    MinimalAgent(governance=RealGovernance(), monitor=monitor).notify_monitor({"type": "Done", "n": 1})
    assert monitor.seen == [("Done", {"type": "Done", "n": 1})]


@pytest.mark.parametrize("monitor", [MonitorFactory.create({}), ConsoleMonitor()], ids=lambda m: type(m).__name__)
def test_notify_monitor_with_shipped_monitors(monitor):
    MinimalAgent(governance=RealGovernance(), monitor=monitor).notify_monitor({"type": "Done"})


def test_agent_cannot_be_given_a_bus():
    """1.26: the constructor refuses a bus, so notify_monitor() can never reach Kafka."""
    with pytest.raises(TypeError, match="without a message bus"):
        MinimalAgent(governance=RealGovernance(), monitor=_Recording(), message_bus=_Bus())


def test_notify_monitor_without_a_monitor_logs(caplog):
    with caplog.at_level(logging.INFO):
        MinimalAgent(governance=RealGovernance()).notify_monitor({"type": "Done"})
    assert any("Event:" in r.message and "Done" in r.message for r in caplog.records)


def test_notify_monitor_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        MinimalAgent(governance=RealGovernance(), monitor=_Recording()).notify_monitor({"type": "Done"})


def test_publish_event_is_removed():
    """Deprecated in 1.24, removed in 1.26."""
    assert not hasattr(MinimalAgent(governance=RealGovernance()), "publish_event")


def test_loop_agents_emit_through_notify_monitor():
    """BaseValidationLoopAgent and BaseCriticActorAgent report their steps without the deprecated name."""
    from k9_aif_abb.k9_agents.critic_actor.base_critic_actor_agent import BaseCriticActorAgent
    from k9_aif_abb.k9_agents.validation.base_validation_loop_agent import BaseValidationLoopAgent
    from types import SimpleNamespace
    from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
    for cls in (BaseValidationLoopAgent, BaseCriticActorAgent):
        monitor = _Recording()
        # Both are abstract; _emit needs only these attributes and BaseAgent's real notify_monitor().
        agent = SimpleNamespace(layer=cls.__name__, monitor=monitor, logger=logging.getLogger("t"))
        agent.notify_monitor = lambda event, _a=agent: BaseAgent.notify_monitor(_a, event)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            cls._emit(agent, "StepDone", {"step": 1})
        assert monitor.seen == [("StepDone", {"type": "StepDone", "agent": cls.__name__, "step": 1})]


def test_cli_templates_run_without_the_deprecated_name():
    """The generated Router template called publish_event(), which BaseRouter does not have."""
    from k9_aif_abb import cli
    src = open(cli.__file__, encoding="utf-8").read()
    assert "self.publish_event(" not in src


def test_no_framework_code_calls_the_deprecated_name():
    """No framework code calls publish_event( (removed in 1.26)."""
    import pathlib
    import k9_aif_abb
    root = pathlib.Path(k9_aif_abb.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("tests/"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "publish_event(" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
