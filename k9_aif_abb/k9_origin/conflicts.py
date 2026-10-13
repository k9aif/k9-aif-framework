# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Conflict rules: k9x Origin flags conflicts; business rules decide what follows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.streams.base_context_state import FieldChange
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope
from k9_aif_abb.k9_origin.config import ConflictWatch


@dataclass
class Conflict:
    """A data conflict on one entity. A fact for business rules, never a decision."""

    entity:    str
    entity_id: str
    kind:      str                      # reversal | late_event | disagreement
    field:     str
    detail:    str
    values:    List[Dict[str, Any]] = field(default_factory=list)   # what conflicted, with time and source
    at:        str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_envelope(self) -> EventEnvelope:
        """The ``origin.conflict`` domain event a Router routes to a review flow."""
        return EventEnvelope(event_type="origin.conflict", source_system="k9x-origin", payload=self.to_dict(),
                             metadata={"key": f"{self.entity}:{self.entity_id}"})


class BaseConflictRule(ABC):
    """ABB: inspect one field change; return a Conflict to flag, or None."""

    @abstractmethod
    def check(self, change: FieldChange) -> Optional[Conflict]:
        raise NotImplementedError


def _iso(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat(timespec="seconds") if ts else None


class TransitionRule(BaseConflictRule):
    """A watched field changing again within the window: either one of the listed transitions
    (``approved -> disapproved``), or, with none listed, any second change in the window."""

    def __init__(self, entity: str, watch: ConflictWatch):
        self.entity, self.watch = entity, watch

    def check(self, change: FieldChange) -> Optional[Conflict]:
        if change.late or change.entity != self.entity or change.field != self.watch.field:
            return None
        if change.previous_at is None or change.old is None:
            return None
        gap = (change.at - change.previous_at).total_seconds()
        if gap > self.watch.within_seconds:
            return None
        if self.watch.transitions and (str(change.old), str(change.new)) not in self.watch.transitions:
            return None
        return Conflict(change.entity, change.entity_id, "reversal", change.field,
                        f"{change.field} changed {change.old} → {change.new} {round(gap, 1)} s after its previous change",
                        [{"value": change.old, "at": _iso(change.previous_at)},
                         {"value": change.new, "at": _iso(change.at), "source": change.source}])


class LateEventRule(BaseConflictRule):
    """An older event arriving after a newer one, with a different value for a watched field."""

    def __init__(self, entity: str, fields: List[str]):
        self.entity, self.fields = entity, set(fields)

    def check(self, change: FieldChange) -> Optional[Conflict]:
        if not change.late or change.entity != self.entity or change.field not in self.fields:
            return None
        if change.new == change.old:
            return None
        return Conflict(change.entity, change.entity_id, "late_event", change.field,
                        f"an older {change.event_type} says {change.field}={change.new}; "
                        f"the current value {change.old} is newer and stands",
                        [{"value": change.old, "at": _iso(change.previous_at), "current": True},
                         {"value": change.new, "at": _iso(change.at), "source": change.source, "late": True}])
