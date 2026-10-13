# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""ContextIngest — the governed path from an event fabric into live context."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

from k9_aif_abb.k9_core.streams.base_context_state import BaseContextState
from k9_aif_abb.k9_core.streams.base_context_window import BaseContextWindow
from k9_aif_abb.k9_core.streams.base_event_fabric import BaseEventFabric
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope
from k9_aif_abb.k9_core.streams.event_governance_gate import EventGovernanceGate, GateDecision

log = logging.getLogger("ContextIngest")

Listener = Callable[[Dict[str, Any]], None]


class ContextIngest:
    """
    Wires the context-fabric ABBs into one governed pipeline::

        fabric.subscribe(topic) → gate.evaluate(event)
            PERMIT / AUDIT / REDACT → state.apply(event) + window.add(event)
            BLOCK                   → state.quarantine(event)   (content never applied)
        → listeners (dashboards, audit, triggers)

    Agents never subscribe to topics; they read the state this keeps current, either
    injected by the Orchestrator (``live_context``) or on demand over MCP
    (``ContextMCPServer``).

    Usage::

        fabric = StreamsFactory.create_fabric(config)
        state  = StreamsFactory.create_state(config, projections=[InvoiceProjection(), ...])
        gate   = StreamsFactory.create_gate(config, governance=ShieldGovernance(config))
        ingest = ContextIngest(fabric, state, gate=gate, window=StreamsFactory.create_window(config))
        ingest.attach(["ap.invoice.updated", "ap.payment.posted"])
    """

    def __init__(self, fabric: Optional[BaseEventFabric], state: BaseContextState,
                 gate: Optional[EventGovernanceGate] = None, window: Optional[BaseContextWindow] = None,
                 listeners: Optional[Iterable[Listener]] = None):
        self.fabric = fabric
        self.state = state
        self.gate = gate
        self.window = window
        self.listeners: List[Listener] = list(listeners or [])
        self.counts: Dict[str, int] = {"permitted": 0, "blocked": 0}

    def attach(self, topics: Iterable[str]) -> None:
        """Subscribe to each topic on the fabric; events arrive through ingest()."""
        if self.fabric is None:
            raise RuntimeError("ContextIngest.attach needs an event fabric (streams.enabled: true)")
        for topic in topics:
            self.fabric.subscribe(topic, lambda env, _t=topic: self.ingest(env, topic=_t))

    def ingest_raw(self, raw: Any, mapper: Any, topic: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """A source that isn't on Kafka (a webhook receiver, a poller) hands its raw
        message here; the mapper turns it into an envelope, then it is gated like any
        event. None when the mapper skips it."""
        envelope = mapper.map(raw, {"topic": topic} if topic else None)
        return self.ingest(envelope, topic=topic) if envelope is not None else None

    def ingest(self, envelope: EventEnvelope, topic: Optional[str] = None) -> Dict[str, Any]:
        """Gate one event, then apply it (or quarantine it). Never raises to the fabric."""
        try:
            result = self.gate.evaluate(envelope) if self.gate else None
            decision = result.decision if result else GateDecision.PERMIT
            if decision == GateDecision.BLOCK:
                keys = self.state.quarantine(envelope, result.reason or "")
                self.counts["blocked"] += 1
                outcome = {"decision": "BLOCK", "reason": result.reason, "entities": keys}
            else:
                governed = result.envelope if result else envelope   # REDACT hands back the redacted event
                keys = self.state.apply(governed)
                if self.window is not None:
                    self.window.add(governed)
                self.counts["permitted"] += 1
                outcome = {"decision": decision.value, "entities": keys}
        except Exception as exc:
            log.exception("[ContextIngest] could not ingest %s", envelope.event_type)
            outcome = {"decision": "ERROR", "reason": str(exc), "entities": []}
        event = {"topic": topic, "envelope": envelope, **outcome,
                 "entities": [f"{e}:{i}" for e, i in outcome["entities"]]}
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:
                log.exception("[ContextIngest] listener failed")
        return event
