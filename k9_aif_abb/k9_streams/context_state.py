# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""InMemoryContextState — live per-entity state for one process (development, demos, tests)."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from k9_aif_abb.k9_core.streams.base_context_state import (
    BaseContextState,
    ContextUpdate,
    ContextValue,
    EntityKey,
    FieldChange,
    event_time,
    event_version,
)
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope


class InMemoryContextState(BaseContextState):
    """
    Live state held in this process. Thread-safe: fabric consumers write from their
    own threads while MCP tools and orchestrators read.

    The topics stay the source of truth: on restart, replay them (a consumer reading
    from the earliest offset) to rebuild the state. Use a Redis or PostgreSQL state
    when several processes must share it.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 projections: Optional[Iterable[Any]] = None):
        super().__init__(config, projections)
        self._lock = threading.Lock()
        self._values: Dict[EntityKey, ContextValue] = {}
        self._history: Dict[EntityKey, deque] = {}

    def _record(self, key: EntityKey, at: datetime, kind: str, fields: Dict[str, Any],
                source: Dict[str, Any]) -> None:
        self._history.setdefault(key, deque(maxlen=self.changes_per_entity)).append(
            {"at": at, "type": kind, "fields": fields, "source": source})

    def _write(self, update: ContextUpdate, envelope: EventEnvelope, source: Dict[str, Any]) -> List[FieldChange]:
        at = event_time(envelope)
        key = update.key
        changes: List[FieldChange] = []
        with self._lock:
            current = self._values.get(key)
            value = dict(current.value) if current else {}
            times = dict(current.field_times) if current else {}
            applied: Dict[str, Any] = {}
            late: Dict[str, Any] = {}
            for name, default in update.defaults.items():
                value.setdefault(name, default)
            for name, new in update.fields.items():
                prev_at = times.get(name)
                if prev_at is not None and at < prev_at:      # older event arriving late
                    late[name] = new
                    changes.append(FieldChange(key[0], key[1], name, value.get(name), new, at, prev_at,
                                               True, envelope.event_type, source))
                    continue
                if value.get(name) != new or name not in value:
                    changes.append(FieldChange(key[0], key[1], name, value.get(name), new, at, prev_at,
                                               False, envelope.event_type, source))
                value[name] = new
                times[name] = at
                applied[name] = new
            for name, item in update.append.items():         # events happened: always recorded
                value[name] = (list(value.get(name) or []) + [item])[-update.append_limit:]
                times[name] = max(times.get(name, at), at)
                applied[name] = item
            newest_before = max(current.field_times.values()) if current and current.field_times else None
            newest = max(times.values()) if times else at
            # source and version follow the newest change by source time, never a late arrival
            leads = current is None or (bool(applied) and (newest_before is None or at >= newest_before))
            self._values[key] = ContextValue(
                update.entity, str(update.entity_id), value,
                newest if (applied or current is None) else current.as_of,
                source if leads else current.source,
                list(current.quarantined) if current else [],
                event_version(envelope) if leads else current.version,
                times,
                current.history_available if current else True)
            if applied:
                self._record(key, at, envelope.event_type, applied, source)
            if late:
                self._record(key, at, f"late:{envelope.event_type}", late, source)
        return changes

    def _mark_quarantined(self, key: EntityKey, marker: Dict[str, Any], source: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            current = self._values.get(key)
            if current is None:
                current = ContextValue(key[0], key[1], {}, now, source)
                self._values[key] = current
            current.quarantined = (current.quarantined + [marker])[-10:]
            current.as_of = now
            self._record(key, now, "quarantined", {"blocked_by": marker["blocked_by"]}, source)

    @staticmethod
    def _copy(cv: ContextValue) -> ContextValue:
        return replace(cv, value=dict(cv.value), source=dict(cv.source), quarantined=list(cv.quarantined),
                       field_times=dict(cv.field_times))

    def mark_history_unavailable(self, key: EntityKey) -> None:
        with self._lock:
            cv = self._values.get(key)
            if cv is not None:
                cv.history_available = False
                self._history.pop(key, None)

    def _read(self, key: EntityKey) -> Optional[ContextValue]:
        with self._lock:
            cv = self._values.get(key)
            return self._copy(cv) if cv else None

    def _scan(self, entity: str) -> List[ContextValue]:
        with self._lock:
            return [self._copy(cv) for key, cv in self._values.items() if key[0] == entity]

    def _changes(self, key: EntityKey) -> List[Dict[str, Any]]:
        with self._lock:   # by source time: a late event sits where it happened, not where it arrived
            return sorted(self._history.get(key, ()), key=lambda c: c["at"])

    def _entity_counts(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for entity, _ in self._values:
                counts[entity] = counts.get(entity, 0) + 1
            return counts

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._history.clear()
