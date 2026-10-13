# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""BaseContextProjection — ABB contract for transforming enterprise events into agent context."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope


class BaseContextProjection(ABC):
    """
    ABB contract for transforming raw enterprise events into agent-usable context.

    A projection is a declarative mapping: source-system schema → agent vocabulary.
    Agents speak domain terms, not SAP IDoc or Salesforce API formats.

    Multiple projections can be registered per stream. The first projection
    whose accepts() returns True is applied.

    Example:
        SAP event:  {"VBELN": "P001", "KBETR": 5000.00, "WAERS": "USD"}
        Projected:  {"policy_id": "P001", "premium": 5000.00, "currency": "USD"}

    SBBs implement one projection per source-system event type.

    Live state (1.17): ``updates()`` turns the projection into ``ContextUpdate``s
    for ``BaseContextState``. By default it keys ``project()``'s result by the
    class attributes ``entity`` and ``id_field``::

        class PolicyProjection(BaseContextProjection):
            entity, id_field = "policy", "policy_id"

    Override ``updates()`` when one event changes several entities, or appends
    to a list (a payment posted changes the invoice and creates a payment).
    """

    entity:   Optional[str] = None
    id_field: Optional[str] = None

    @abstractmethod
    def accepts(self, envelope: EventEnvelope) -> bool:
        """
        Return True if this projection handles the given event.
        Called before project() to determine applicability.
        """
        raise NotImplementedError

    @abstractmethod
    def project(self, envelope: EventEnvelope) -> Dict[str, Any]:
        """
        Transform the event envelope payload into an agent-consumable dict.
        Must not raise — return {} if the projection cannot be applied.
        """
        raise NotImplementedError

    def updates(self, envelope: EventEnvelope) -> List[Any]:
        """The ContextUpdates this event makes to live state (none by default)."""
        if not (self.entity and self.id_field):
            return []
        entity_id = (envelope.payload or {}).get(self.id_field)
        if entity_id is None:
            return []
        from k9_aif_abb.k9_core.streams.base_context_state import ContextUpdate
        return [ContextUpdate(self.entity, str(entity_id), self.project(envelope))]
