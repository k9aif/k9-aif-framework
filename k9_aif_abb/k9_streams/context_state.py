# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""InMemoryContextState — live per-entity state for one process (development, demos, tests)."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from k9_aif_abb.k9_core.streams.base_context_state import (
    BaseContextState,
    ContextUpdate,
    ContextValue,
    EntityKey,
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

    def _write(self, update: ContextUpdate, envelope: EventEnvelope, source: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        key = update.key
        with self._lock:
            current = self._values.get(key)
            value = dict(current.value) if current else {}
            for name, default in update.defaults.items():
                value.setdefault(name, default)
            value.update(update.fields)
            for name, item in update.append.items():
                value[name] = (list(value.get(name) or []) + [item])[-update.append_limit:]
            self._values[key] = ContextValue(update.entity, str(update.entity_id), value, now, source,
                                             list(current.quarantined) if current else [])
            changed = {**update.fields, **{k: v for k, v in update.append.items()}}
            self._record(key, now, envelope.event_type, changed, source)

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

    def _read(self, key: EntityKey) -> Optional[ContextValue]:
        with self._lock:
            cv = self._values.get(key)
            return ContextValue(cv.entity, cv.entity_id, dict(cv.value), cv.as_of, dict(cv.source),
                                list(cv.quarantined)) if cv else None

    def _scan(self, entity: str) -> List[ContextValue]:
        with self._lock:
            return [ContextValue(cv.entity, cv.entity_id, dict(cv.value), cv.as_of, dict(cv.source),
                                 list(cv.quarantined))
                    for key, cv in self._values.items() if key[0] == entity]

    def _changes(self, key: EntityKey) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history.get(key, ()))

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
