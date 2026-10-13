# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""BaseContextState — ABB contract for live, per-entity enterprise state built from streams."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope

EntityKey = Tuple[str, str]   # (entity, entity_id): ("invoice", "INV-1001")


@dataclass
class ContextUpdate:
    """One change a projection derives from an event, for one entity.

    fields   merged into the entity's current value (last write wins per field)
    append   each item appended to a list field (payments, notes), newest last
    defaults set only when the field is absent (e.g. a vendor's status "ok")
    """

    entity:       str
    entity_id:    str
    fields:       Dict[str, Any] = field(default_factory=dict)
    append:       Dict[str, Any] = field(default_factory=dict)
    defaults:     Dict[str, Any] = field(default_factory=dict)
    append_limit: int            = 50

    @property
    def key(self) -> EntityKey:
        return (self.entity, str(self.entity_id))


@dataclass
class ContextValue:
    """The current value of one entity, with when it last changed and which event set it."""

    entity:      str
    entity_id:   str
    value:       Dict[str, Any]
    as_of:       datetime
    source:      Dict[str, Any]       = field(default_factory=dict)
    quarantined: List[Dict[str, Any]] = field(default_factory=list)
    version:     Optional[str]        = None
    # Source time of the last applied change per field: a later-arriving but older event
    # never overwrites a field set by a newer one (apply by source order, not arrival).
    field_times: Dict[str, datetime]  = field(default_factory=dict)
    history_available: bool           = True

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        return round(((now or _now()) - self.as_of).total_seconds(), 1)

    def view(self, now: Optional[datetime] = None, max_age_seconds: Optional[float] = None) -> Dict[str, Any]:
        """What an agent receives: the value plus as_of, age, staleness and provenance."""
        age = self.age_seconds(now)
        out = {"entity": self.entity, "id": self.entity_id, "found": True, "value": dict(self.value),
               "as_of": _iso(self.as_of), "age_seconds": age,
               "stale": bool(max_age_seconds is not None and age > max_age_seconds),
               "source": dict(self.source), "version": self.version}
        if not self.history_available:
            out["history_available"] = False
        if self.quarantined:
            out["quarantined"] = [dict(q) for q in self.quarantined]
        return out


@dataclass
class FieldChange:
    """One field of one entity changed (or was refused as late). Reported to change listeners;
    k9x Origin's conflict rules run on these."""

    entity:      str
    entity_id:   str
    field:       str
    old:         Any
    new:         Any
    at:          datetime            # source time of the event
    previous_at: Optional[datetime]  # source time of the field's previous change
    late:        bool                # older than the field's current value: recorded, not applied
    event_type:  str
    source:      Dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


_BLOCKED_BY = re.compile(r"\[([A-Za-z0-9_]+)\]")


class BaseContextState(ABC):
    """
    ABB contract for the live state agents reason about: the latest value of each
    enterprise entity (an invoice, a vendor, a policy), folded from a stream of events.

    A context window (``BaseContextWindow``) answers "which events happened"; the
    context state answers "what is true right now, and since when". Every answer
    carries ``as_of`` (when the value last changed), ``age_seconds`` and ``stale``
    (older than ``max_age_seconds``), plus the source event, so an agent can refuse
    to act on old data and every decision can be traced to the record behind it.

    Projections (``BaseContextProjection``) turn events into ``ContextUpdate``s; the
    state applies them. Events refused by the fabric's ``EventGovernanceGate`` are
    never applied: ``quarantine()`` only marks the entities they concern, so an
    agent knows untrusted data arrived for them and can send the case to a human.

    Read side (also served over MCP by ``ContextMCPServer``):
      get_current(entity, id)            latest value, as_of, age, stale, source
      recent_changes(entity, id, secs)   what changed in the last secs, oldest first
      query(entity, filters, minimum)    entities of one type, filtered

    SBBs implement the storage primitives: InMemoryContextState (k9_streams);
    a Redis or PostgreSQL state for multi-process deployments.

    YAML config::

        streams:
          state:
            max_age_seconds: 120     # older values are reported stale
            changes_per_entity: 50   # recent changes kept per entity
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 projections: Optional[Iterable[Any]] = None):
        self.config = config or {}
        state_cfg = (self.config.get("streams") or {}).get("state") or {}
        max_age = state_cfg.get("max_age_seconds")
        self.max_age_seconds: Optional[float] = float(max_age) if max_age is not None else None
        self.changes_per_entity: int = int(state_cfg.get("changes_per_entity", 50))
        self.projections: List[Any] = list(projections or [])
        self.change_listeners: List[Callable[[FieldChange], None]] = []

    def register_projection(self, projection: Any) -> None:
        self.projections.append(projection)

    # ── write side ──────────────────────────────────────────────────────
    def updates_for(self, envelope: EventEnvelope) -> List[ContextUpdate]:
        """Every update the registered projections derive from one event."""
        updates: List[ContextUpdate] = []
        for projection in self.projections:
            if projection.accepts(envelope):
                updates.extend(projection.updates(envelope))
        return updates

    def apply(self, envelope: EventEnvelope) -> List[EntityKey]:
        """Fold one governed event into the state; return the entities it changed."""
        changed = []
        for update in self.updates_for(envelope):
            for change in self._write(update, envelope, _source(envelope)) or []:
                self._notify(change)
            changed.append(update.key)
        return changed

    def _notify(self, change: FieldChange) -> None:
        for listener in self.change_listeners:
            try:
                listener(change)
            except Exception:   # a listener never breaks ingestion
                import logging
                logging.getLogger("BaseContextState").exception("change listener failed")

    def quarantine(self, envelope: EventEnvelope, reason: str) -> List[EntityKey]:
        """Mark the entities a refused event concerns. Its content is never applied."""
        blocked_by = _BLOCKED_BY.search(reason or "")
        marker = {"event_id": envelope.event_id, "event_type": envelope.event_type,
                  "blocked_by": blocked_by.group(1) if blocked_by else "governance", "at": _iso(_now())}
        keys = []
        for update in self.updates_for(envelope):
            if update.key not in keys:
                keys.append(update.key)
                self._mark_quarantined(update.key, marker, _source(envelope))
        return keys

    @abstractmethod
    def _write(self, update: ContextUpdate, envelope: EventEnvelope, source: Dict[str, Any]) -> List[FieldChange]:
        """Merge one update into the entity's value by source time (``event_time``): a field is
        set only if the event is not older than that field's current value; appends always
        apply (the event happened). Record the change; return the field changes, late ones
        flagged, for the change listeners."""
        raise NotImplementedError

    @abstractmethod
    def _mark_quarantined(self, key: EntityKey, marker: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Record that an event for this entity was refused, without its content."""
        raise NotImplementedError

    # ── storage reads ───────────────────────────────────────────────────
    @abstractmethod
    def _read(self, key: EntityKey) -> Optional[ContextValue]:
        raise NotImplementedError

    @abstractmethod
    def _scan(self, entity: str) -> List[ContextValue]:
        raise NotImplementedError

    @abstractmethod
    def _changes(self, key: EntityKey) -> List[Dict[str, Any]]:
        """Recorded changes for one entity, oldest first: {"at": datetime, "type", "fields", "source"}."""
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError

    # ── read side ───────────────────────────────────────────────────────
    def get_current(self, entity: str, entity_id: str) -> Dict[str, Any]:
        value = self._read((entity, str(entity_id)))
        if value is None:
            return {"entity": entity, "id": str(entity_id), "found": False, "as_of": None}
        return value.view(max_age_seconds=self.max_age_seconds)

    def recent_changes(self, entity: str, entity_id: str, window_seconds: float = 600) -> Dict[str, Any]:
        now = _now()
        items = [c for c in self._changes((entity, str(entity_id)))
                 if (now - c["at"]).total_seconds() <= window_seconds]
        return {"entity": entity, "id": str(entity_id), "window_seconds": window_seconds, "as_of": _iso(now),
                "changes": [{"at": _iso(c["at"]), "seconds_ago": round((now - c["at"]).total_seconds(), 1),
                             "type": c["type"], "fields": c["fields"], "source": c["source"]} for c in items]}

    def query(self, entity: str, filters: Optional[Dict[str, Any]] = None,
              minimum: Optional[Dict[str, float]] = None, limit: int = 200) -> Dict[str, Any]:
        """Entities of one type whose fields equal ``filters`` and are at least ``minimum``."""
        now = _now()
        rows = []
        for cv in sorted(self._scan(entity), key=lambda v: v.entity_id):
            val = cv.value
            if any(v not in (None, "") and val.get(k) != v for k, v in (filters or {}).items()):
                continue
            if any(_num(val.get(k)) < float(v) for k, v in (minimum or {}).items() if v):
                continue
            rows.append(cv.view(now, self.max_age_seconds))
        return {"entity": entity, "as_of": _iso(now), "count": len(rows), "rows": rows[:limit]}

    def snapshot(self) -> Dict[str, Any]:
        """Entity counts by type, for dashboards and the Orchestrator's audit trail."""
        return {"as_of": _iso(_now()), "entities": self._entity_counts()}

    def _entity_counts(self) -> Dict[str, int]:
        return {}


def event_time(envelope: EventEnvelope) -> datetime:
    """When the change happened at its source (the envelope's timestamp), timezone-aware."""
    ts = envelope.timestamp or _now()
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def event_version(envelope: EventEnvelope) -> Optional[str]:
    """The source's own ordering key, for conditional actions: an explicit metadata version,
    else a CDC log position, else the transport position, else the event id."""
    meta = envelope.metadata if isinstance(envelope.metadata, dict) else {}
    if meta.get("version"):
        return str(meta["version"])
    cdc = meta.get("cdc") or {}
    if cdc.get("lsn") is not None:
        return f"{cdc.get('db') or 'db'}:lsn:{cdc['lsn']}"
    t = meta.get("transport") or {}
    if t.get("offset") is not None:
        return f"{t.get('topic')}:{t.get('partition', 0)}:{t['offset']}"
    return envelope.event_id


def _source(envelope: EventEnvelope) -> Dict[str, Any]:
    src = {"event_id": envelope.event_id, "event_type": envelope.event_type,
           "source_system": envelope.source_system}
    transport = envelope.metadata.get("transport") if isinstance(envelope.metadata, dict) else None
    if isinstance(transport, dict):
        src.update({k: transport[k] for k in ("topic", "partition", "offset") if k in transport})
    return src


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
