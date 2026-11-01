# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.23: a consumed event is never skipped, and a HIL decision always resumes its flow.

- Kafka consumers commit an offset only after the event is handled or dead-lettered
  (k9_core/messaging/delivery.py); before, offsets were committed on a timer and a failed
  handler was logged, so the event was skipped for good.
- G-18: the Router marked a paused flow resolved before re-routing it, so a crash between
  the two lost the resume. Now the decision is stored with a claim, the row is resolved only
  after re-routing, a failed re-route releases the claim, and a recovery sweep finishes a claim
  whose Router stopped.

Each behaviour test fails on 1.22.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, Text, inspect

from k9_aif_abb.k9_core.messaging.delivery import (DeliveryError, PermanentMessageError,
                                                 handle_with_retry)
from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage

CONFIG = {"routing": {"table": {"fraud_alert": "fraud.in"},
                      "hil": {"prefix": "hil.", "resume_lease_seconds": 300}}}


class _Bus:
    def __init__(self, fail_times=0):
        self.published, self.fail_times = [], fail_times

    def publish_to(self, topic: str, event: Dict[str, Any]):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("broker unavailable")
        self.published.append((topic, event))


def _store():
    return RoutingStateStore(db=SQLiteDatabaseStorage(db_path=":memory:"))


def _paused(store, cid="HIL-1"):
    store.record_hil_pending(correlation_id=cid, orchestrator_module="m", orchestrator_class="C",
                             reply_to="hil.replies.fraud",
                             payload={"event_type": "fraud_alert", "alert_id": "A-1"})
    return {"correlation_id": cid, "action": "approve", "actor": "reviewer@bank.example"}


def _resumed(bus):
    return [e for t, e in bus.published if t == "fraud.in" and "hil_decision" in e]


# ── delivery helper ─────────────────────────────────────────────────────────────────────

def test_a_transient_failure_is_retried_until_it_succeeds():
    calls, dlq = [], []

    def handle():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("store down")

    out = handle_with_retry(handle, topic="t", msg=SimpleNamespace(offset=7),
                            dead_letter=lambda q, e: dlq.append(q), sleep=lambda s: None)
    assert out == "handled" and len(calls) == 3 and dlq == []


def test_an_undecodable_message_is_dead_lettered_at_once():
    calls, dlq = [], []

    def handle():
        calls.append(1)
        raise PermanentMessageError("not JSON")

    out = handle_with_retry(handle, topic="t", msg=SimpleNamespace(offset=1, value=b"\xff"),
                            dead_letter=lambda q, e: dlq.append((q, e)), sleep=lambda s: None)
    assert out == "dead_lettered" and len(calls) == 1 and dlq[0][0] == "t.dlq"
    assert dlq[0][1]["reason"].startswith("PermanentMessageError")


def test_a_failed_dead_letter_publish_raises_so_nothing_is_committed():
    def dead_letter(q, e):
        raise ConnectionError("broker down")

    with pytest.raises(DeliveryError):
        handle_with_retry(lambda: (_ for _ in ()).throw(ValueError("x")), topic="t",
                          msg=SimpleNamespace(offset=1), dead_letter=dead_letter,
                          attempts=2, sleep=lambda s: None)


# ── G-18: a decision always resumes its flow ─────────────────────────────────────────────

def test_a_failed_reroute_releases_the_claim_and_the_redelivered_reply_resumes():
    store, bus = _store(), _Bus(fail_times=1)
    router = K9EventRouter(config=CONFIG, message_bus=bus, state_store=store)
    reply = _paused(store)
    with pytest.raises(ConnectionError):
        asyncio.run(router._on_hil_reply(dict(reply)))      # the bus will deliver it again
    assert store.get_hil_pending("HIL-1")["status"] == "pending"
    asyncio.run(router._on_hil_reply(dict(reply)))
    assert len(_resumed(bus)) == 1
    assert store.get_hil_pending("HIL-1")["status"] == "resolved"


def test_a_resume_interrupted_by_a_crash_is_finished_by_the_recovery_sweep():
    store, bus = _store(), _Bus()
    reply = _paused(store)
    # A Router claimed the flow (decision stored) and stopped before re-routing it.
    assert store.begin_hil_resume("HIL-1", reply, lease_seconds=300)
    cfg = {**CONFIG, "routing": {**CONFIG["routing"], "hil": {"prefix": "hil.", "resume_lease_seconds": 0}}}
    router = K9EventRouter(config=cfg, message_bus=bus, state_store=store)
    assert router.recover_stalled_hil() == 1
    resumed = _resumed(bus)
    assert len(resumed) == 1 and resumed[0]["hil_decision"]["actor"] == "reviewer@bank.example"
    assert store.get_hil_pending("HIL-1")["status"] == "resolved"
    assert router.recover_stalled_hil() == 0


def test_a_live_claim_is_not_taken_over_by_the_sweep_or_a_duplicate_reply():
    store, bus = _store(), _Bus()
    router = K9EventRouter(config=CONFIG, message_bus=bus, state_store=store)
    reply = _paused(store)
    assert store.begin_hil_resume("HIL-1", reply, lease_seconds=300)   # another Router, still working
    assert router.recover_stalled_hil() == 0
    asyncio.run(router._on_hil_reply(dict(reply)))
    assert _resumed(bus) == []


def test_a_reply_without_correlation_id_is_dead_lettered_not_dropped():
    router = K9EventRouter(config=CONFIG, message_bus=_Bus(), state_store=_store())
    with pytest.raises(PermanentMessageError):
        asyncio.run(router._on_hil_reply({"action": "approve"}))


def test_a_reply_with_no_state_store_is_retried_not_dropped():
    router = K9EventRouter(config=CONFIG, message_bus=_Bus(), state_store=_store())
    router.state_store = None
    with pytest.raises(RuntimeError, match="no state_store"):
        asyncio.run(router._on_hil_reply({"correlation_id": "HIL-1", "action": "approve"}))


def test_listening_without_a_bus_raises():
    router = K9EventRouter(config=CONFIG, message_bus=None, state_store=_store())
    with pytest.raises(RuntimeError, match="HIL replies cannot be consumed"):
        asyncio.run(router.listen_for_hil_replies())


def test_an_existing_hil_pending_table_gains_the_resume_columns(tmp_path):
    path = tmp_path / "old.db"
    db = SQLiteDatabaseStorage(db_path=str(path))
    md = MetaData()
    Table("hil_pending", md,                                     # the pre-1.23 shape
          Column("correlation_id", String, primary_key=True), Column("orchestrator_module", String),
          Column("orchestrator_class", String), Column("reply_to", String), Column("reason", Text),
          Column("priority", String), Column("payload", JSON), Column("status", String),
          Column("created_at", DateTime), Column("resolved_at", DateTime))
    md.create_all(db.engine)
    store = RoutingStateStore(db=SQLiteDatabaseStorage(db_path=str(path)))
    cols = {c["name"] for c in inspect(store.db.engine).get_columns("hil_pending")}
    assert {"decision", "resuming_at"} <= cols
    _paused(store, "HIL-9")
    assert store.begin_hil_resume("HIL-9", {"action": "approve"})


# ── streams fabric ───────────────────────────────────────────────────────────────────────

def test_the_streams_fabric_commits_only_after_an_event_is_projected(monkeypatch):
    from k9_aif_abb.k9_streams import kafka_stream

    class Consumer(list):
        commits = 0

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    msgs = Consumer([SimpleNamespace(topic="orders", partition=0, offset=i, key=None,
                                     value=json.dumps({"id": i}).encode()) for i in range(2)])
    monkeypatch.setattr("kafka.KafkaConsumer", lambda *a, **k: msgs)
    fabric = kafka_stream.KafkaEventFabric.__new__(kafka_stream.KafkaEventFabric)
    fabric._kafka_cfg = {"group_id": "ctx", "delivery_attempts": 2}
    fabric._consumers, fabric._consumer_threads, fabric.unmapped = {}, {}, {}
    fabric._producer = MagicMock()
    fabric._bootstrap_servers = lambda: ["localhost:9092"]
    fabric._security_kwargs = lambda: {}
    fabric._mapper_for = lambda t: SimpleNamespace(map=lambda v, tr: SimpleNamespace(metadata={}, v=v))
    fabric._ensure_producer = lambda: None

    seen = []

    def project(env):
        if env.v["id"] == 0:
            raise ValueError("projection failed")
        seen.append(env.v["id"])

    fabric.subscribe("orders", project)
    fabric._consumer_threads["orders"].join(timeout=10)
    dlq = [c for c in fabric._producer.send.call_args_list if c.args[0] == "orders.dlq"]
    assert seen == [1] and len(dlq) == 1 and msgs.commits == 2


# ── object storage ──────────────────────────────────────────────────────────────────────

def test_exists_is_false_only_for_a_missing_object_and_raises_on_an_outage():
    from k9_aif_abb.k9_core.storage.base_object_storage import BaseObjectStorage

    class Store(BaseObjectStorage):
        def __init__(self, error):
            self.error = error

        def upload(self, *a, **k): ...
        def download(self, bucket, key):
            raise self.error
        def delete(self, *a, **k): ...
        def list_objects(self, *a, **k): return []
        def get_uri(self, bucket, key): return f"mem://{bucket}/{key}"

    assert Store(FileNotFoundError("gone")).exists("b", "k") is False
    with pytest.raises(ConnectionError):
        Store(ConnectionError("endpoint unreachable")).exists("b", "k")
