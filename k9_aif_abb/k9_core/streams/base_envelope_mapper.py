# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""BaseEnvelopeMapper — ABB contract for turning a source's raw message into an EventEnvelope."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope


class BaseEnvelopeMapper(ABC):
    """
    Sources don't speak K9-AIF. A database's change data capture emits Debezium change
    records, a log shipper emits log lines, a SaaS webhook posts its own JSON. A mapper
    turns one raw message into an ``EventEnvelope`` so the rest of the context fabric —
    gate, projections, live state, MCP — works the same for every source.

    ``map()`` receives the decoded message (a dict for JSON, else a str; ``None`` for a
    Kafka tombstone) and the transport details (``topic``, ``partition``, ``offset``,
    ``key``). Return ``None`` to skip a message that carries no event (a tombstone, a
    heartbeat). Never raise for a malformed message: return ``None`` and let the fabric
    count it as unmapped.

    OOB mappers (k9_streams.envelope_mappers): native, debezium, log_line, auto.
    Register your own with ``StreamsFactory.register_mapper(name, cls)``.

    YAML config (per topic; ``default`` for the rest)::

        streams:
          mappers:
            default: auto
            dbserver.public.invoices: debezium
            app-logs: {type: log_line, source_system: billing-api}
    """

    name: str = "base"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def map(self, raw: Any, transport: Optional[Dict[str, Any]] = None) -> Optional[EventEnvelope]:
        """One raw message → an EventEnvelope, or None to skip it."""
        raise NotImplementedError
