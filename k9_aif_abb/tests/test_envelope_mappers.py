# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Envelope mappers (1.17): raw source messages → EventEnvelope, per topic."""

from types import SimpleNamespace

import pytest

from k9_aif_abb.k9_core.streams import BaseContextProjection, EventEnvelope
from k9_aif_abb.k9_factories.streams_factory import StreamsFactory
from k9_aif_abb.k9_streams import (
    AutoEnvelopeMapper,
    ContextIngest,
    DebeziumEnvelopeMapper,
    InMemoryContextState,
    LogLineEnvelopeMapper,
    NativeEnvelopeMapper,
)
from k9_aif_abb.k9_streams.envelope_mappers import decode_value

SOURCE = {"version": "2.7.0.Final", "connector": "postgresql", "name": "dbserver", "ts_ms": 1760300000000,
          "db": "ap", "schema": "public", "table": "invoices"}


def change(op, before=None, after=None):
    return {"before": before, "after": after, "source": SOURCE, "op": op, "ts_ms": 1760300000123}


# ── Debezium ─────────────────────────────────────────────────────────────
def test_debezium_update_maps_row_table_and_change_time():
    env = DebeziumEnvelopeMapper().map(change("u", {"invoice_id": "INV-1", "status": "approved"},
                                              {"invoice_id": "INV-1", "status": "paid"}),
                                       {"topic": "dbserver.public.invoices", "offset": 7})
    assert env.event_type == "invoices.updated" and env.source_system == "ap"
    assert env.payload == {"invoice_id": "INV-1", "status": "paid"}
    assert env.timestamp.year == 2025 and env.metadata["cdc"]["op"] == "u"
    assert env.metadata["transport"]["offset"] == 7 and "before" not in env.metadata["cdc"]


def test_debezium_schema_wrapper_create_snapshot_delete_and_tombstone():
    m = DebeziumEnvelopeMapper({"source_system": "erp", "include_before": True})
    wrapped = {"schema": {"type": "struct"}, "payload": change("c", None, {"invoice_id": "INV-2"})}
    assert m.map(wrapped).event_type == "invoices.created" and m.map(wrapped).source_system == "erp"
    assert m.map(change("r", None, {"invoice_id": "INV-3"})).event_type == "invoices.snapshot"
    deleted = m.map(change("d", {"invoice_id": "INV-4", "status": "void"}, None))
    assert deleted.event_type == "invoices.deleted" and deleted.payload == {"invoice_id": "INV-4", "status": "void",
                                                                             "_deleted": True}
    assert deleted.metadata["cdc"]["before"]["invoice_id"] == "INV-4"
    assert m.map(None) is None and m.map("not json") is None and m.map({"op": "x"}) is None


def test_debezium_mongodb_json_string_rows():
    rec = {"before": None, "after": '{"_id": "V-1", "status": "flagged"}', "op": "c",
           "source": {"connector": "mongodb", "db": "vendors", "collection": "vendor"}, "ts_ms": 1760300000000}
    env = DebeziumEnvelopeMapper().map(rec)
    assert env.event_type == "vendor.created" and env.payload == {"_id": "V-1", "status": "flagged"}


def test_debezium_rows_feed_a_projection_into_live_state():
    class InvoiceRow(BaseContextProjection):
        entity, id_field = "invoice", "invoice_id"

        def accepts(self, env):
            return env.event_type.startswith("invoices.")

        def project(self, env):
            return env.payload

    state = InMemoryContextState(projections=[InvoiceRow()])
    ingest = ContextIngest(None, state)
    out = ingest.ingest_raw(change("u", None, {"invoice_id": "INV-9", "status": "paid"}), DebeziumEnvelopeMapper(),
                            topic="dbserver.public.invoices")
    assert out["entities"] == ["invoice:INV-9"]
    cur = state.get_current("invoice", "INV-9")
    assert cur["value"]["status"] == "paid" and cur["source"]["source_system"] == "ap"
    assert ingest.ingest_raw(None, DebeziumEnvelopeMapper()) is None


# ── log lines ────────────────────────────────────────────────────────────
def test_log_line_plain_text_json_and_shipper_wrapped():
    m = LogLineEnvelopeMapper({"source_system": "billing-api"})
    plain = m.map("2026-10-12T14:03:22.481Z ERROR payments.release Payment PAY-77 rejected by bank")
    assert plain.event_type == "log.error" and plain.source_system == "billing-api"
    assert plain.payload["logger"] == "payments.release" and plain.payload["message"].startswith("Payment PAY-77")
    assert plain.timestamp.year == 2026 and plain.timestamp.tzinfo is not None

    js = m.map({"level": "WARN", "message": "retrying", "invoice_id": "INV-1"})
    assert js.event_type == "log.warn" and js.payload["invoice_id"] == "INV-1"

    filebeat = m.map({"@timestamp": "2026-10-12T14:03:22Z", "message": "2026-10-12 14:03:22 INFO api started",
                      "host": {"name": "web-1"}})
    assert filebeat.event_type == "log.info" and filebeat.payload["host"] == {"name": "web-1"}

    free = m.map("something odd happened")
    assert free.event_type == "log.line" and free.payload == {"message": "something odd happened"}
    assert m.map("   ") is None and m.map(None) is None


def test_log_line_custom_pattern():
    m = LogLineEnvelopeMapper({"pattern": r"^\[(?P<level>\w+)\] (?P<message>.*)$"})
    env = m.map("[audit] user ravi approved INV-3")
    assert env.event_type == "log.audit" and env.payload["message"] == "user ravi approved INV-3"


# ── native and auto ─────────────────────────────────────────────────────
def test_native_and_auto():
    native = EventEnvelope(event_type="invoice.created", source_system="ap", payload={"invoice_id": "INV-1"}).to_dict()
    assert NativeEnvelopeMapper().map(native).payload == {"invoice_id": "INV-1"}
    assert NativeEnvelopeMapper().map({"no": "type"}) is None
    auto = AutoEnvelopeMapper()
    assert auto.map(native).event_type == "invoice.created"
    assert auto.map(change("u", None, {"invoice_id": "INV-1"})).event_type == "invoices.updated"
    assert auto.map("a log line") is None and auto.map(None) is None


def test_decode_value():
    assert decode_value(b'{"a": 1}') == {"a": 1}
    assert decode_value(b"plain line") == "plain line"
    assert decode_value(None) is None


# ── per-topic configuration and the Kafka message path ──────────────────
def test_factory_mapper_per_topic():
    cfg = {"streams": {"mappers": {"default": "auto", "app-logs": {"type": "log_line", "source_system": "billing"},
                                   "dbserver.public.invoices": "debezium"}}}
    assert isinstance(StreamsFactory.create_mapper(cfg, "other"), AutoEnvelopeMapper)
    logs = StreamsFactory.create_mapper(cfg, "app-logs")
    assert isinstance(logs, LogLineEnvelopeMapper) and logs.config["source_system"] == "billing"
    assert isinstance(StreamsFactory.create_mapper(cfg, "dbserver.public.invoices"), DebeziumEnvelopeMapper)
    assert isinstance(StreamsFactory.create_mapper({}, "t"), AutoEnvelopeMapper)
    with pytest.raises(ValueError):
        StreamsFactory.create_mapper({"streams": {"mappers": {"default": "nope"}}}, "t")


def test_kafka_fabric_maps_raw_messages_and_counts_unmapped():
    from k9_aif_abb.k9_streams.kafka_stream import KafkaEventFabric

    fab = KafkaEventFabric({"streams": {"mappers": {"app-logs": "log_line"}}})
    msg = SimpleNamespace(topic="app-logs", partition=0, offset=42, key=b"web-1",
                          value=b"2026-10-12T14:03:22Z ERROR api.pay timeout")
    env = fab._to_envelope(fab._mapper_for("app-logs"), msg)
    assert env.event_type == "log.error"
    assert env.metadata["transport"] == {"topic": "app-logs", "partition": 0, "offset": 42, "key": "web-1"}

    other = SimpleNamespace(topic="misc", partition=0, offset=1, key=None, value=b"not an event")
    assert fab._to_envelope(fab._mapper_for("misc"), other) is None and fab.unmapped == {"misc": 1}
