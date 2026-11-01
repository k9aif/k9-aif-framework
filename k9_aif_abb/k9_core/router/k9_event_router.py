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

import asyncio
import logging
import re
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.messaging.delivery import PermanentMessageError
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
        # 1.23: how long a resume claim is held before the recovery sweep may take it over
        self.hil_resume_lease_seconds: float = float(hil_cfg.get("resume_lease_seconds", 300))

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
            # 1.23: raise, as route() does without a bus; returning left every decision unconsumed
            raise RuntimeError(f"[{self.layer}] no pattern-capable message_bus: HIL replies cannot be "
                               "consumed. Pass message_bus= (K9EventBus).")
        sweep = asyncio.create_task(self._recovery_sweep_forever())
        try:
            await self.message_bus.subscribe_async(
                self._on_hil_reply, pattern=self._hil_reply_pattern
            )
        finally:
            sweep.cancel()

    async def _recovery_sweep_forever(self) -> None:
        """Run :meth:`recover_stalled_hil` at start and every half lease (1.23)."""
        while True:
            try:
                await asyncio.to_thread(self.recover_stalled_hil)
            except Exception as exc:
                log.error("[%s] HIL recovery sweep failed (retried next pass): %s", self.layer, exc)
            await asyncio.sleep(max(self.hil_resume_lease_seconds / 2, 1.0))

    def recover_stalled_hil(self) -> int:
        """Re-route flows whose resume was claimed but never finished (the Router stopped between
        recording the decision and re-routing; G-18, closed in 1.23). Each is claimed again under
        a new lease, so two Routers never resume the same flow at once. Returns how many resumed."""
        if not self.state_store:
            return 0
        resumed = 0
        for row in self.state_store.stalled_hil_resumes(self.hil_resume_lease_seconds):
            cid = row["correlation_id"]
            decision = row.get("decision") or {}
            if not self.state_store.begin_hil_resume(cid, decision, self.hil_resume_lease_seconds):
                continue
            log.warning("[%s] HIL correlation_id=%s: resume did not finish; re-routing with the "
                        "recorded decision", self.layer, cid)
            self._resume(cid, row, decision)
            resumed += 1
        return resumed

    def _resume(self, correlation_id: str, pending: Dict[str, Any], decision: Dict[str, Any]) -> None:
        """Re-route a claimed flow; release the claim if routing fails, finish it if it succeeds."""
        resumed_payload = {**(pending.get("payload") or {}), "hil_decision": decision}
        log.info("[%s] HIL reply correlation_id=%s resolved -> re-routing event_type=%r",
                 self.layer, correlation_id, resumed_payload.get("event_type"))
        try:
            self.route(resumed_payload)
        except Exception:
            self.state_store.release_hil_resume(correlation_id)
            raise
        self.state_store.finish_hil_resume(correlation_id)

    async def _on_hil_reply(self, message: Dict[str, Any]) -> None:
        correlation_id = message.get("correlation_id")
        if not correlation_id:
            # 1.23: dead-lettered by the bus (permanent), not silently dropped
            raise PermanentMessageError(f"[{self.layer}] HIL reply has no correlation_id")

        if not self.state_store:
            # 1.23: raised, so the bus retries and then dead-letters it instead of skipping it
            raise RuntimeError(f"[{self.layer}] HIL reply correlation_id={correlation_id}: "
                               "no state_store configured, cannot resolve")

        pending = self.state_store.get_hil_pending(correlation_id)
        if not pending:
            log.warning(
                "[%s] HIL reply correlation_id=%s matches no pending flow "
                "(unknown correlation_id)", self.layer, correlation_id,
            )
            return

        # G-16: the atomic gate, not an optimization -- begin_hil_resume() is a
        # compare-and-swap (pending -> resuming) and only this call's winner re-routes. A
        # duplicate reply (Kafka redelivery, the HIL outbox's retry, a second Router) finds the
        # row resuming or resolved and is dropped.
        # G-18 (closed in 1.23): the claim stores the decision, and the row is marked resolved
        # only after route() succeeds. A failed route() releases the claim and raises, so the bus
        # delivers the reply again; a crash leaves the claim to the recovery sweep.
        if not self.state_store.begin_hil_resume(correlation_id, message, self.hil_resume_lease_seconds):
            log.info(
                "[%s] HIL reply correlation_id=%s already resolved or being resumed -- "
                "dropping duplicate, not re-routing", self.layer, correlation_id,
            )
            return
        self._resume(correlation_id, pending, message)

    # ------------------------------------------------------------------
    def _dispatch(self, topic: str, payload: Dict[str, Any], strategy: str = "") -> None:
        """Publish payload to the given topic via message_bus."""
        if not self.message_bus:
            # route() would otherwise report routed: True for an event that went nowhere (1.19.0)
            raise RuntimeError(f"[{self.layer}] no message_bus: cannot publish event_type="
                               f"{payload.get('event_type')!r} to {topic}. Pass message_bus= (K9EventBus or "
                               f"MessageFactory.create(config)), or use BaseRouter for direct calls.")
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
