# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9EventRouter — OOB Kafka-aware event router.

The Router is the **single entry point** for all events.  It never contains
classification logic — routing is either deterministic (event_type in the
routing table) or delegated to the IntentOrchestrator via the intent topic.

Routing logic
-------------
1. ``event_type`` found in ``routing.table`` config  →  publish to domain topic
2. ``event_type`` not found                          →  publish to ``intent.in``
   IntentOrchestrator picks it up, classifies intent, re-publishes to the
   correct domain topic (or sends a "please clarify" response).

Configuration (``config.yaml``)
--------------------------------
::

    routing:
      intent_topic: intent.in          # fallback topic when intent unknown
      table:                           # event_type → topic mappings
        claims_submitted: claims.in
        fraud_alert:      fraud.in
        doc_uploaded:     documents.in

SBB override
------------
Extend and override ``route()`` for custom routing logic::

    class AcmeRouter(K9EventRouter):
        layer = "AcmeRouter SBB"

        def route(self, payload):
            # add pre-routing enrichment, auth checks, etc.
            payload = self._enrich(payload)
            return super().route(payload)
"""

import logging
import re
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.router.base_router import BaseRouter

log = logging.getLogger(__name__)


class K9EventRouter(BaseRouter):
    """
    OOB event router — deterministic routing with IntentOrchestrator fallback.
    """

    layer = "K9EventRouter OOB"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
        message_bus=None,
        governance=None,
        state_store=None,
    ):
        super().__init__(
            config=config,
            monitor=monitor,
            message_bus=message_bus,
            governance=governance,
        )
        routing_cfg = self.config.get("routing", {})
        self._table: Dict[str, str] = routing_cfg.get("table", {})
        self._intent_topic: str = routing_cfg.get("intent_topic", "intent.in")

        hil_cfg = routing_cfg.get("hil", {})
        self._hil_prefix: str = hil_cfg.get("prefix", "hil.")
        self._hil_reply_pattern: str = hil_cfg.get(
            "reply_pattern", re.escape(self._hil_prefix) + r"replies\..*"
        )
        self.state_store = state_store or self._bootstrap_state_store(self.config)

        log.info(
            "[%s] routing table: %d entries | intent_topic=%s | hil_reply_pattern=%s",
            self.layer, len(self._table), self._intent_topic, self._hil_reply_pattern,
        )

    @staticmethod
    def _bootstrap_state_store(config: Dict[str, Any]):
        """Same zero-config SQLite default as BaseHILOrchestrator — the
        Router and the HIL Orchestrator must agree on where pending
        correlations live, or a reply never finds the row it's meant to
        resolve. Pass state_store= explicitly to share a real store
        (Postgres, or the same in-process instance) across both."""
        try:
            from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage
            from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore

            db_path = (
                config.get("hil", {}).get("db_path")
                or config.get("persistence", {}).get("db_path")
                or "./runtime/hil_pending.db"
            )
            db = SQLiteDatabaseStorage(db_path=db_path)
            return RoutingStateStore(db=db)
        except Exception as exc:
            log.warning(
                "[K9EventRouter] no state_store configured and default bootstrap "
                "failed (%s) -- HIL replies cannot be resolved", exc,
            )
            return None

    def route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route the event.

        Returns a dict with:
          ``routed``    — always True
          ``topic``     — topic the event was published to
          ``event_type``— original event_type from payload
          ``strategy``  — "deterministic" or "intent_required"
        """
        event_type = payload.get("event_type", "")
        topic = self._table.get(event_type)

        if topic:
            log.info("[%s] deterministic: event_type=%r → %s", self.layer, event_type, topic)
            self._dispatch(topic, payload, strategy="deterministic")
            return {
                "routed": True,
                "topic": topic,
                "event_type": event_type,
                "strategy": "deterministic",
            }

        log.info(
            "[%s] non-deterministic: event_type=%r not in table → %s",
            self.layer, event_type, self._intent_topic,
        )
        self._dispatch(self._intent_topic, payload, strategy="intent_required")
        return {
            "routed": True,
            "topic": self._intent_topic,
            "event_type": event_type,
            "strategy": "intent_required",
        }

    # ------------------------------------------------------------------
    # HIL reply handling
    #
    # One consumer, subscribed to a topic *pattern* (hil.replies.*), not
    # one process per orchestrator/queue -- job-id belongs in the message
    # (correlation_id), never in the topic name. See CLAUDE.md's HIL
    # section and BaseHILOrchestrator's own topic-convention docstring.
    # ------------------------------------------------------------------
    async def listen_for_hil_replies(self) -> None:
        """Long-running consumer loop -- run this as its own asyncio task
        alongside whatever normally feeds route(). Resolves each reply by
        correlation_id against state_store's hil_pending table and
        re-routes the resumed payload through the Router's own route(),
        same as any other event -- resuming is just re-routing with new
        information now available, not a separate mechanism."""
        if not self.message_bus or not hasattr(self.message_bus, "subscribe_async"):
            log.warning(
                "[%s] no pattern-capable message_bus configured -- "
                "HIL replies cannot be consumed", self.layer,
            )
            return
        await self.message_bus.subscribe_async(
            self._on_hil_reply, pattern=self._hil_reply_pattern
        )

    async def _on_hil_reply(self, message: Dict[str, Any]) -> None:
        correlation_id = message.get("correlation_id")
        if not correlation_id:
            log.warning("[%s] HIL reply missing correlation_id, dropped: %r",
                        self.layer, message)
            return

        if not self.state_store:
            log.error(
                "[%s] HIL reply correlation_id=%s received but no state_store "
                "configured -- cannot resolve", self.layer, correlation_id,
            )
            return

        pending = self.state_store.get_hil_pending(correlation_id)
        if not pending:
            log.warning(
                "[%s] HIL reply correlation_id=%s matches no pending flow "
                "(unknown correlation_id)", self.layer, correlation_id,
            )
            return

        # G-16: the atomic gate, not an optimization -- resolve_hil_pending()
        # is a compare-and-swap (status='pending' -> 'resolved', WHERE
        # status='pending') and only re-routes if *this* call is the one
        # that actually made the transition. A duplicate reply (Kafka's
        # own at-least-once redelivery, or an outbox immediate-attempt/
        # sweep race on the publishing side -- see hil_reply.py) finds
        # the row already resolved, resolve_hil_pending() returns False,
        # and this drops it instead of re-routing a flow that already
        # resumed once. Also protects two Router instances racing on the
        # same reply -- only one of them wins the UPDATE.
        if not self.state_store.resolve_hil_pending(correlation_id):
            log.info(
                "[%s] HIL reply correlation_id=%s already resolved -- "
                "dropping duplicate, not re-routing", self.layer, correlation_id,
            )
            return

        resumed_payload = {**(pending.get("payload") or {}), "hil_decision": message}
        log.info(
            "[%s] HIL reply correlation_id=%s resolved -> re-routing "
            "event_type=%r", self.layer, correlation_id,
            resumed_payload.get("event_type"),
        )
        self.route(resumed_payload)

    # ------------------------------------------------------------------
    def _dispatch(self, topic: str, payload: Dict[str, Any], strategy: str = "") -> None:
        """Publish payload to the given topic via message_bus."""
        if self.message_bus:
            if hasattr(self.message_bus, "publish_to"):
                self.message_bus.publish_to(topic, payload)
            else:
                self.message_bus.publish(payload)
        if self.monitor:
            self.monitor.record_event({
                "type": "EventRouted",
                "event_type": payload.get("event_type"),
                "topic": topic,
                "strategy": strategy,
            })
