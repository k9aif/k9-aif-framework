# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Proves the full HIL round trip designed across this session:

    Router --route()--> Orchestrator --RequiresHIL--> BaseHILOrchestrator
        (publish hil.requests.<queue> + persist pending state)
    ... human decision arrives on hil.replies.<queue> ...
    Router (_on_hil_reply) --resolve correlation_id--> re-route() the
        resumed payload, same as any other event

No live Kafka broker -- a fake message_bus captures publish_to() calls,
and the reply side is driven directly (calling _on_hil_reply()) rather
than through a real aiokafka pattern-consumer, matching how
test_orchestrator_shield_governance.py exercises BaseOrchestrator without
needing real infrastructure. RoutingStateStore is real (SQLite in-memory),
not mocked -- this is exactly the persistence path the whole design
depends on, worth proving for real per the framework's own "no faking"
verification standard.
"""

import asyncio
from typing import Any, Dict

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage


class _FakeMessageBus:
    """Captures publish_to() calls instead of touching real Kafka."""

    def __init__(self):
        self.published = []  # list[(topic, event)]

    def publish_to(self, topic: str, event: Dict[str, Any]):
        self.published.append((topic, event))

    def publish(self, event: Dict[str, Any]):
        self.published.append((None, event))


class _FraudOrchestrator(BaseOrchestrator):
    """Minimal SBB-shaped orchestrator -- raises RequiresHIL itself rather
    than via a real Squad/Agent chain, keeping this test scoped to the
    Router <-> HIL Orchestrator round trip specifically (Agent/Squad
    propagation through BaseSquad.execute()'s try/except-reraise is a
    separate, already-verified code path, not re-proven here)."""

    layer = "FraudOrchestrator"

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if payload.get("fraud_probability", 0) > 0.8:
                raise RequiresHIL(
                    reason="fraud_probability exceeds auto-approve threshold",
                    context={"alert_id": payload.get("alert_id")},
                    priority="high",
                )
            return {"status": "completed", "decision": "auto-approved"}
        except RequiresHIL as exc:
            return self.handle_requires_hil(exc, payload)


def _make_store() -> RoutingStateStore:
    db = SQLiteDatabaseStorage(db_path=":memory:")
    return RoutingStateStore(db=db)


def test_hil_roundtrip_router_to_orchestrator_and_back():
    store = _make_store()
    bus = _FakeMessageBus()

    config = {
        "k9_env": "test",
        "routing": {
            "table": {"fraud_alert": "fraud.in"},
            "hil": {"prefix": "hil."},
        },
    }

    router = K9EventRouter(config=config, message_bus=bus, state_store=store)
    orchestrator = _FraudOrchestrator(
        config=config, message_bus=bus, hil_state_store=store,
    )

    incoming = {
        "event_type": "fraud_alert",
        "alert_id": "ALT-1001",
        "fraud_probability": 0.91,
    }

    # 1. Router dispatches the initial event to the domain topic.
    routed = router.route(incoming)
    assert routed["topic"] == "fraud.in"

    # 2. Orchestrator halts instead of completing -- RequiresHIL caught,
    #    delegated to BaseHILOrchestrator.
    result = orchestrator.execute_flow(incoming)
    assert result["status"] == "pending_hil"
    correlation_id = result["correlation_id"]
    assert result["reply_to"] == "hil.replies.fraudorchestrator"

    # 3. The HIL request was actually published, not just described.
    request_topics = [t for t, _ in bus.published]
    assert "hil.requests.fraudorchestrator" in request_topics

    # 4. Enough state was persisted to resume -- not just a topic name.
    pending = store.get_hil_pending(correlation_id)
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["payload"]["alert_id"] == "ALT-1001"
    assert pending["reason"] == "fraud_probability exceeds auto-approve threshold"

    # 5. Simulate the human decision arriving on the reply topic --
    #    driven directly against the Router's handler rather than a real
    #    Kafka consumer loop (the loop itself is aiokafka's contract, not
    #    this framework's logic).
    hil_decision = {
        "correlation_id": correlation_id,
        "action": "approve",
        "actor": "reviewer@bank.example",
    }
    asyncio.run(router._on_hil_reply(hil_decision))

    # 6. Router re-routed the resumed payload back through route() --
    #    same topic the original event went to, HIL decision merged in.
    resumed_events = [e for t, e in bus.published if t == "fraud.in"]
    assert len(resumed_events) == 2  # step 1's dispatch + this resume
    resumed = resumed_events[-1]
    assert resumed["alert_id"] == "ALT-1001"
    assert resumed["hil_decision"]["action"] == "approve"
    assert resumed["hil_decision"]["actor"] == "reviewer@bank.example"

    # 7. Marked resolved -- not left pending forever.
    resolved = store.get_hil_pending(correlation_id)
    assert resolved["status"] == "resolved"


def test_hil_not_triggered_on_clean_payload():
    """Regression guard: the common case must still complete normally,
    never accidentally routed through HIL."""
    store = _make_store()
    bus = _FakeMessageBus()
    config = {"k9_env": "test", "routing": {"hil": {"prefix": "hil."}}}

    orchestrator = _FraudOrchestrator(
        config=config, message_bus=bus, hil_state_store=store,
    )
    result = orchestrator.execute_flow({
        "event_type": "fraud_alert", "alert_id": "ALT-2002", "fraud_probability": 0.1,
    })

    assert result["status"] == "completed"
    assert bus.published == []


def test_hil_reply_with_unknown_correlation_id_is_dropped_not_raised():
    """A reply for a correlation_id nothing is waiting on (already
    resolved, or from a different Router instance) must be logged and
    dropped, never raise -- a stray/duplicate Kafka message shouldn't be
    able to crash the Router's consumer loop."""
    store = _make_store()
    bus = _FakeMessageBus()
    router = K9EventRouter(
        config={"k9_env": "test", "routing": {"hil": {"prefix": "hil."}}},
        message_bus=bus,
        state_store=store,
    )

    asyncio.run(router._on_hil_reply({"correlation_id": "does-not-exist"}))

    assert bus.published == []
