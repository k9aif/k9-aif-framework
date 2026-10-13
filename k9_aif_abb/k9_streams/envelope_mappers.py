# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Envelope mappers for common sources: native envelopes, Debezium change records, log lines."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.streams.base_envelope_mapper import BaseEnvelopeMapper
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope

_DEBEZIUM_OPS = {"c": "created", "r": "snapshot", "u": "updated", "d": "deleted", "t": "truncated"}


def _with_transport(envelope: EventEnvelope, transport: Optional[Dict[str, Any]]) -> EventEnvelope:
    if transport:
        envelope.metadata = {**(envelope.metadata or {}), "transport": dict(transport)}
    return envelope


class NativeEnvelopeMapper(BaseEnvelopeMapper):
    """Messages already in K9-AIF form: a dict with ``event_type`` (and ``source_system``)."""

    name = "native"

    def map(self, raw: Any, transport: Optional[Dict[str, Any]] = None) -> Optional[EventEnvelope]:
        if not isinstance(raw, dict) or not raw.get("event_type"):
            return None
        data = dict(raw)
        data.setdefault("source_system", self.config.get("source_system", "unknown"))
        try:
            return _with_transport(EventEnvelope.from_dict(data), transport)
        except (KeyError, TypeError, ValueError):
            return None


class DebeziumEnvelopeMapper(BaseEnvelopeMapper):
    """
    Debezium change records (PostgreSQL, MySQL, SQL Server, Oracle, MongoDB connectors), with
    or without the JSON-converter schema wrapper.

    event_type   ``<table>.<created|snapshot|updated|deleted|truncated>``, e.g. ``invoices.updated``
    payload      the row after the change; for a delete, the row before with ``"_deleted": true``
    source_system  ``source_system`` from config, else the connector's database name
    timestamp    the change time (``ts_ms``), so ``as_of`` reflects the database, not the consumer
    metadata["cdc"]  op, table, schema, db, connector, before (when ``include_before``)

    Projections then key the row like any event::

        class InvoiceProjection(BaseContextProjection):
            entity, id_field = "invoice", "invoice_id"
            def accepts(self, env): return env.event_type.startswith("invoices.")
            def project(self, env): return env.payload
    """

    name = "debezium"

    def map(self, raw: Any, transport: Optional[Dict[str, Any]] = None) -> Optional[EventEnvelope]:
        record = self._record(raw)
        if record is None:
            return None
        op = record.get("op")
        source = record.get("source") or {}
        before, after = _row(record.get("before")), _row(record.get("after"))   # MongoDB sends JSON strings
        table = source.get("table") or source.get("collection") or "table"
        if op == "d":
            row = {**(before or {}), "_deleted": True}
        else:
            row = dict(after or {})
        ts_ms = record.get("ts_ms") or source.get("ts_ms")
        cdc = {"op": op, "table": table, "schema": source.get("schema"), "db": source.get("db"),
               "connector": source.get("connector"), "lsn": source.get("lsn", source.get("pos"))}
        if self.config.get("include_before") and before is not None:
            cdc["before"] = before
        envelope = EventEnvelope(
            event_type=f"{table}.{_DEBEZIUM_OPS[op]}",
            source_system=self.config.get("source_system") or source.get("db") or source.get("name") or "cdc",
            payload=row,
            timestamp=_from_ms(ts_ms),
            metadata={"cdc": cdc, **({"version": f"{source.get('db') or 'db'}:lsn:{cdc['lsn']}"}
                                     if cdc["lsn"] is not None else {})},
        )
        return _with_transport(envelope, transport)

    @staticmethod
    def _record(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None   # tombstone (None) or not JSON
        if "payload" in raw and isinstance(raw.get("payload"), dict) and "schema" in raw:
            raw = raw["payload"]   # JSON converter with schemas.enable=true
        if raw.get("op") not in _DEBEZIUM_OPS or not isinstance(raw.get("source"), dict):
            return None
        return raw

    @classmethod
    def looks_like(cls, raw: Any) -> bool:
        return cls._record(raw) is not None


class LogLineEnvelopeMapper(BaseEnvelopeMapper):
    """
    Application log lines, as shipped by Fluent Bit, Vector or Filebeat.

    JSON lines become the payload as they are; plain text is parsed with ``pattern``
    (named groups; default ``<timestamp> <LEVEL> <logger> <message>``), falling back to
    ``{"message": line}``. event_type is ``log.<level>`` (``log.line`` without a level);
    a parseable ISO timestamp becomes the envelope's timestamp.

    Config: ``source_system`` (default ``app-logs``), ``pattern``, ``level_field``
    (default ``level``), ``message_field`` (default ``message``; Filebeat ships the line here).
    """

    name = "log_line"
    DEFAULT_PATTERN = (r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
                       r"(?P<level>[A-Za-z]+)\s+(?P<logger>\S+)\s+(?P<message>.*)$")

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.pattern = re.compile(self.config.get("pattern") or self.DEFAULT_PATTERN)
        self.level_field = self.config.get("level_field", "level")
        self.message_field = self.config.get("message_field", "message")

    def map(self, raw: Any, transport: Optional[Dict[str, Any]] = None) -> Optional[EventEnvelope]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            fields = dict(raw)
            line = fields.get(self.message_field)
            if isinstance(line, str) and set(fields) <= {self.message_field, "@timestamp", "host", "log", "agent",
                                                          "ecs", "input", "fields"}:
                parsed = self._parse(line)   # a shipper wrapped a plain-text line
                if parsed:
                    fields = {**parsed, **{k: v for k, v in fields.items() if k != self.message_field}}
        else:
            text = str(raw).rstrip("\n")
            if not text.strip():
                return None
            fields = self._parse(text) or {"message": text}
        level = str(fields.get(self.level_field) or "").lower()
        ts = _parse_ts(fields.get("timestamp") or fields.get("@timestamp"))
        envelope = EventEnvelope(
            event_type=f"log.{level}" if level else "log.line",
            source_system=self.config.get("source_system", "app-logs"),
            payload=fields,
            timestamp=ts or datetime.now(timezone.utc),
        )
        return _with_transport(envelope, transport)

    def _parse(self, line: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
        m = self.pattern.match(line)
        return {k: v for k, v in m.groupdict().items() if v is not None} if m else None


class AutoEnvelopeMapper(BaseEnvelopeMapper):
    """Default: a native envelope, else a Debezium change record, else skipped (unmapped)."""

    name = "auto"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.mappers: List[BaseEnvelopeMapper] = [NativeEnvelopeMapper(config), DebeziumEnvelopeMapper(config)]

    def map(self, raw: Any, transport: Optional[Dict[str, Any]] = None) -> Optional[EventEnvelope]:
        for mapper in self.mappers:
            envelope = mapper.map(raw, transport)
            if envelope is not None:
                return envelope
        return None


def decode_value(value: Optional[bytes]) -> Any:
    """Kafka message bytes → dict (JSON object), str (anything else), or None (tombstone)."""
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, (bytes, bytearray)) else str(value)
    try:
        return json.loads(text)
    except ValueError:
        return text


def _row(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {"value": value}
    return value if isinstance(value, dict) or value is None else {"value": value}


def _from_ms(ts_ms: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00").replace(",", "."))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


BUILTIN_MAPPERS = {m.name: m for m in (NativeEnvelopeMapper, DebeziumEnvelopeMapper,
                                       LogLineEnvelopeMapper, AutoEnvelopeMapper)}
