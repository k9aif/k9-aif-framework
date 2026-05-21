# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — EOCRouter (SBB)
#
# Main event router. Receives events from the frontend/API,
# determines intent deterministically from event_type, and
# publishes to the correct Kafka topic for the target orchestrator.
#
# Hierarchy: EOCRouter → Kafka topic → Orchestrator → Squad → Agents

import logging
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus
from k9_aif_abb.k9_core.router.base_router import BaseRouter


log = logging.getLogger(__name__)


# Deterministic routing table: event_type → Kafka topic
_ROUTING_TABLE: Dict[str, str] = {
    "claim_submitted":             "eoc-claims",
    "document_received":           "eoc-documents",
    "fraud_signal_raised":         "eoc-fraud",
    "policy_change_requested":     "eoc-policy",
    "catastrophe_alert_issued":    "eoc-catastrophe",
    "customer_interaction_logged": "eoc-customer",
    "audit_query_received":        "eoc-audit",
}


class EOCRouter(BaseRouter):
    """
    EOC Event Router (SBB).

    Extends ``BaseRouter`` so zero trust fires before every publish.

    The main entry point for all enterprise events. Receives an event
    from the frontend or API, inspects the ``event_type`` field, and
    publishes the full payload to the correct Kafka topic so the
    appropriate squad orchestrator can consume it.

    No business logic lives here — routing is purely deterministic.

    Routing table::

        claim_submitted             → eoc-claims
        document_received           → eoc-documents
        fraud_signal_raised         → eoc-fraud
        policy_change_requested     → eoc-policy
        catastrophe_alert_issued    → eoc-catastrophe
        customer_interaction_logged → eoc-customer
        audit_query_received        → eoc-audit

    Usage::

        router = EOCRouter(config)
        router.route("claim_submitted", payload)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        zt_enabled = cfg.get("governance", {}).get("enabled", False)
        super().__init__(config=cfg, enable_zero_trust=zt_enabled)

        messaging = self.config.get("messaging", {})
        brokers = messaging.get("brokers", ["localhost:9092"])
        self._broker = brokers[0] if isinstance(brokers, list) else brokers

        # One K9EventBus per outbound topic
        self._buses: Dict[str, K9EventBus] = {
            event_type: K9EventBus(
                broker_url=self._broker,
                topic=topic,
                group_id="eoc-router",
            )
            for event_type, topic in _ROUTING_TABLE.items()
        }

        log.info(
            "[EOCRouter] Initialized | broker=%s | routes=%d | zero_trust=%s",
            self._broker,
            len(self._buses),
            zt_enabled,
        )

    # ------------------------------------------------------------------
    def route(self, event_type: str, payload: Dict[str, Any]) -> bool:
        """
        Route an event to the correct Kafka topic.

        Args:
            event_type: The type of event (e.g. ``"claim_submitted"``).
                        Case-insensitive.
            payload:    The full event payload including all context,
                        uploaded document references, correlation_id, etc.

        Returns:
            True if the event was routed, False if no route was found.
        """
        key = event_type.lower().strip()
        bus = self._buses.get(key)

        if bus is None:
            log.warning(
                "[EOCRouter] No route for event_type=%r. Known types: %s",
                event_type,
                list(_ROUTING_TABLE.keys()),
            )
            return False

        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            log.warning(
                "[EOCRouter] Zero Trust DENIED event_type=%s reason=%s risk=%s",
                event_type, zt["reason"], zt["risk_score"],
            )
            return False

        topic = _ROUTING_TABLE[key]
        log.info(
            "[EOCRouter] Routing event_type=%s → topic=%s | correlation_id=%s",
            event_type,
            topic,
            payload.get("correlation_id", ""),
        )
        bus.publish({**zt["payload"], "event_type": key})
        return True

    # ------------------------------------------------------------------
    def supported_event_types(self) -> list:
        """Return the list of event types this router can handle."""
        return list(_ROUTING_TABLE.keys())

    # ------------------------------------------------------------------
    def close(self) -> None:
        """Gracefully shut down all Kafka producers."""
        for bus in self._buses.values():
            bus.close()
        log.info("[EOCRouter] Shutdown complete.")
