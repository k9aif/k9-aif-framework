# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ToolCallAuditLog: every intercepted tool call, every decision, who made it and when.

Two kinds of record:

- events, append-only: ``intercepted``, ``denied``, ``executed``, ``rejected`` ...
  Nothing updates or deletes an event.
- pending calls waiting for a person, keyed by ``correlation_id``. A pending call
  moves between states only through ``transition()``, a compare-and-swap, so a
  duplicate reply or a second process can't run the same call twice:

      pending -> executing -> executed | failed
      pending -> rejected | expired | malformed

``SQLiteToolCallAuditLog`` is the zero-config default (``./runtime/tool_calls.db``,
like the HIL state store's default). ``InMemoryToolCallAuditLog`` is for tests.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional


class BaseToolCallAuditLog(ABC):
    """ABB: append-only events plus pending calls with atomic state changes."""

    @abstractmethod
    def record(self, correlation_id: str, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Append one event. Never updates an earlier one."""

    @abstractmethod
    def create_pending(self, correlation_id: str, record: Dict[str, Any]) -> None:
        """Store a call waiting for review (status ``pending``)."""

    @abstractmethod
    def get_pending(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """The stored call and its state, or None."""

    @abstractmethod
    def transition(self, correlation_id: str, from_states: Iterable[str], to_state: str,
                   **fields: Any) -> bool:
        """Move a pending call to ``to_state`` only if it is in one of ``from_states``.
        True if this call made the change; False if another one already had."""

    @abstractmethod
    def events(self, correlation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Events in the order they were recorded."""

    @abstractmethod
    def pending_before(self, deadline: float) -> List[Dict[str, Any]]:
        """Calls still ``pending`` whose ``expires_at`` is before ``deadline``."""


class InMemoryToolCallAuditLog(BaseToolCallAuditLog):
    def __init__(self):
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._pending: Dict[str, Dict[str, Any]] = {}

    def record(self, correlation_id, event, data=None):
        with self._lock:
            self._events.append({"correlation_id": correlation_id, "event": event,
                                 "data": dict(data or {}), "at": time.time()})

    def create_pending(self, correlation_id, record):
        with self._lock:
            if correlation_id in self._pending:
                raise ValueError(f"tool call {correlation_id} is already pending")
            self._pending[correlation_id] = {**record, "correlation_id": correlation_id, "status": "pending"}

    def get_pending(self, correlation_id):
        with self._lock:
            row = self._pending.get(correlation_id)
            return dict(row) if row else None

    def transition(self, correlation_id, from_states, to_state, **fields):
        with self._lock:
            row = self._pending.get(correlation_id)
            if not row or row["status"] not in set(from_states):
                return False
            row.update(fields)
            row["status"] = to_state
            return True

    def events(self, correlation_id=None):
        with self._lock:
            return [dict(e) for e in self._events
                    if correlation_id is None or e["correlation_id"] == correlation_id]

    def pending_before(self, deadline):
        with self._lock:
            return [dict(r) for r in self._pending.values()
                    if r["status"] == "pending" and r.get("expires_at", float("inf")) < deadline]


class SQLiteToolCallAuditLog(BaseToolCallAuditLog):
    """Durable default. One file; safe across threads of one process and across
    processes sharing the file (SQLite serialises writers)."""

    def __init__(self, db_path: str = "./runtime/tool_calls.db"):
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL") if db_path != ":memory:" else None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tool_call_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT NOT NULL,
                event TEXT NOT NULL,
                data TEXT NOT NULL,
                at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tool_call_pending (
                correlation_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                expires_at REAL,
                record TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS tool_call_events_no_update
                BEFORE UPDATE ON tool_call_events
                BEGIN SELECT RAISE(ABORT, 'tool_call_events is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS tool_call_events_no_delete
                BEFORE DELETE ON tool_call_events
                BEGIN SELECT RAISE(ABORT, 'tool_call_events is append-only'); END;
            """
        )

    def record(self, correlation_id, event, data=None):
        with self._lock:
            self._conn.execute(
                "INSERT INTO tool_call_events (correlation_id, event, data, at) VALUES (?, ?, ?, ?)",
                (correlation_id, event, json.dumps(data or {}, default=str), time.time()))

    def create_pending(self, correlation_id, record):
        row = {**record, "correlation_id": correlation_id, "status": "pending"}
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO tool_call_pending (correlation_id, status, expires_at, record) VALUES (?, ?, ?, ?)",
                    (correlation_id, "pending", record.get("expires_at"), json.dumps(row, default=str)))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"tool call {correlation_id} is already pending") from exc

    def get_pending(self, correlation_id):
        with self._lock:
            cur = self._conn.execute(
                "SELECT status, record FROM tool_call_pending WHERE correlation_id = ?", (correlation_id,))
            hit = cur.fetchone()
        if not hit:
            return None
        row = json.loads(hit[1])
        row["status"] = hit[0]
        return row

    def transition(self, correlation_id, from_states, to_state, **fields):
        states = list(from_states)
        marks = ",".join("?" for _ in states)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    f"SELECT record FROM tool_call_pending WHERE correlation_id = ? AND status IN ({marks})",
                    (correlation_id, *states))
                hit = cur.fetchone()
                if not hit:
                    self._conn.execute("ROLLBACK")
                    return False
                row = {**json.loads(hit[0]), **fields, "status": to_state}
                self._conn.execute(
                    "UPDATE tool_call_pending SET status = ?, record = ? WHERE correlation_id = ?",
                    (to_state, json.dumps(row, default=str), correlation_id))
                self._conn.execute("COMMIT")
                return True
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def events(self, correlation_id=None):
        sql = "SELECT correlation_id, event, data, at FROM tool_call_events"
        args: tuple = ()
        if correlation_id is not None:
            sql, args = sql + " WHERE correlation_id = ?", (correlation_id,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [{"correlation_id": c, "event": e, "data": json.loads(d), "at": a} for c, e, d, a in rows]

    def pending_before(self, deadline):
        with self._lock:
            rows = self._conn.execute(
                "SELECT record FROM tool_call_pending WHERE status = 'pending' AND expires_at < ?",
                (deadline,)).fetchall()
        return [json.loads(r[0]) for r in rows]
