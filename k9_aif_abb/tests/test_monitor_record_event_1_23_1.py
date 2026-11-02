# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
1.23.1: every shipped monitor accepts record_event().

BaseAgent.publish_event(), BaseOrchestrator.publish_status() and K9EventRouter.route() hand
their event to ``monitor.record_event()``, but no monitor defined it, so with any real monitor
attached the call raised AttributeError (the router's after the event was already on Kafka).
The earlier tests used MagicMock, which accepts any method, so they never saw it. These tests
use the real monitor classes and no mocks.
"""

from typing import Any, Dict

import pytest

from k9_aif_abb.k9_core.monitoring.base_monitoring import BaseMonitor
from k9_aif_abb.k9_core.monitoring.logger_monitor import LoggerMonitor
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter
from k9_aif_abb.k9_factories.monitor_factory import MonitorFactory
from k9_aif_abb.k9_monitoring.console_monitor import ConsoleMonitor
from k9_aif_abb.tests.test_delivery_and_resume_1_23 import CONFIG, _Bus, _store
from k9_aif_abb.tests.test_framework import MinimalAgent, RealGovernance


def _real_monitors():
    monitors = [MonitorFactory.create({}), ConsoleMonitor(), LoggerMonitor()]
    try:
        from k9_aif_abb.k9_monitoring.prometheus_monitor import PrometheusMonitor
        monitors.append(PrometheusMonitor())
    except Exception:  # prometheus_client not installed in this environment
        pass
    return monitors


class _Recording(BaseMonitor):
    """A real BaseMonitor subclass that keeps what observe() receives."""

    def __init__(self):
        super().__init__(name="recording")
        self.seen = []

    def emit_metric(self, name, value, tags=None):
        pass

    def observe(self, event, meta=None):
        self.seen.append((event, meta))


class _Orchestrator(BaseOrchestrator):
    layer = "Test Orchestrator"

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}


@pytest.mark.parametrize("monitor", _real_monitors(), ids=lambda m: type(m).__name__)
def test_agent_publish_event_with_a_real_monitor(monitor):
    agent = MinimalAgent(governance=RealGovernance(), monitor=monitor)
    agent.publish_event({"type": "TestEvent"})


@pytest.mark.parametrize("monitor", _real_monitors(), ids=lambda m: type(m).__name__)
def test_orchestrator_publish_status_with_a_real_monitor(monitor):
    _Orchestrator(config={}, monitor=monitor, governance=RealGovernance()).publish_status("done", {"job": "J-1"})


def test_router_records_after_publishing_without_raising():
    bus, monitor = _Bus(), _Recording()
    router = K9EventRouter(config=CONFIG, message_bus=bus, state_store=_store(), monitor=monitor)
    result = router.route({"event_type": "fraud_alert", "alert_id": "A-1"})
    assert result["routed"] is True
    assert len(bus.published) == 1                       # published once, and route() returned normally
    assert monitor.seen == [("EventRouted", {"type": "EventRouted", "event_type": "fraud_alert",
                                             "topic": "fraud.in", "strategy": "deterministic"})]


def test_record_event_names_the_observation_by_type_then_status():
    monitor = _Recording()
    monitor.record_event({"type": "RetrievalCompleted", "hits": 3})
    monitor.record_event({"status": "completed", "job": "J-1"})
    monitor.record_event({"job": "J-2"})
    assert [name for name, _ in monitor.seen] == ["RetrievalCompleted", "completed", "event"]
    assert monitor.seen[0][1] == {"type": "RetrievalCompleted", "hits": 3}
