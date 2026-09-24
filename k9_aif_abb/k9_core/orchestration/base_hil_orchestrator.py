# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
BaseHILOrchestrator -- OOB, concrete-enough-to-use-directly Orchestrator
whose job is packaging and publishing a human-review request, and
persisting enough state to resume the originating flow once a decision
comes back.

Deliberately a real, invocable Orchestrator (not a helper method mixed
into BaseOrchestrator) -- a conscious, second carve-out of the "no
Orchestrator calls another Orchestrator" rule, same spirit as the Kafka-
ownership carve-out for RequiresHIL documented in CLAUDE.md. One shared,
testable place owns "how does this framework talk to HIL", instead of
every orchestrator that might need human review hand-rolling topic names
and correlation-id bookkeeping itself.

Topic convention
-----------------
    hil.requests.<queue>   -- published here by execute_flow()
    hil.replies.<queue>    -- where this specific request's decision is
                              expected; the Router subscribes to the
                              pattern ``hil\\.replies\\..*`` across every
                              queue, dispatching by correlation_id, not by
                              which exact topic a reply arrived on.

``queue`` defaults to a slugified form of the *catching* orchestrator's
``layer`` (e.g. "AGN3FraudOrchestrator" -> "agn3fraudorchestrator") when
``RequiresHIL`` doesn't specify one explicitly -- so a fraud-detection
orchestrator's HIL requests land in a fraud-shaped queue without the
raise site needing to know the queue name.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

log = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "default"


class BaseHILOrchestrator(BaseOrchestrator):
    """
    OOB HIL Orchestrator.

    ``execute_flow(payload)`` expects a payload shaped like the ``ctx``
    dict ``BaseOrchestrator.handle_requires_hil()`` builds from a caught
    ``RequiresHIL`` -- see that method for the exact keys. Publishes the
    request, persists pending state via ``state_store`` (a
    ``RoutingStateStore``-shaped collaborator), and returns immediately
    -- never blocks waiting for a decision. A HIL review can take hours
    or days; nothing in this framework holds a process open that long.
    """

    layer = "BaseHILOrchestrator OOB"

    def __init__(self, *args, state_store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_store = state_store or self._bootstrap_state_store(self.config)

    @staticmethod
    def _bootstrap_state_store(config: Dict[str, Any]):
        """Zero-config default: SQLite-backed RoutingStateStore, same
        fallback shape as the framework's other persistence bootstraps.
        Pass ``state_store=`` explicitly (e.g. a Postgres-backed one) for
        production; this exists so BaseHILOrchestrator is usable OOB with
        no config at all, matching every other factory's zero-config
        default."""
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
                "[%s] no state_store configured and default bootstrap failed "
                "(%s) -- pending HIL flows will not survive a restart",
                "BaseHILOrchestrator OOB", exc,
            )
            return None

    # ------------------------------------------------------------------
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        queue = payload.get("queue") or _slugify(payload.get("source_orchestrator", "default"))

        hil_cfg = self.config.get("routing", {}).get("hil", {})
        prefix = hil_cfg.get("prefix", "hil.")
        request_topic = f"{prefix}requests.{queue}"
        reply_topic = f"{prefix}replies.{queue}"

        message = {
            "correlation_id": correlation_id,
            "reply_to": reply_topic,
            "title": payload.get("title") or payload.get("reason", "Human review requested"),
            "description": payload.get("reason"),
            "priority": payload.get("priority", "medium"),
            "source_orchestrator": payload.get("source_orchestrator"),
            "payload": payload.get("context", {}),
        }

        if self.message_bus and hasattr(self.message_bus, "publish_to"):
            self.message_bus.publish_to(request_topic, message)
        else:
            self.logger.warning(
                "[%s] no message_bus configured -- HIL request not published (correlation_id=%s)",
                self.layer, correlation_id,
            )

        if self.state_store:
            self.state_store.record_hil_pending(
                correlation_id=correlation_id,
                orchestrator_module=payload.get("resume_module", ""),
                orchestrator_class=payload.get("resume_class", ""),
                reply_to=reply_topic,
                payload=payload.get("resume_payload", payload.get("context", {})),
                reason=payload.get("reason"),
                priority=payload.get("priority", "medium"),
            )

        self.publish_status("pending_hil", {
            "correlation_id": correlation_id,
            "queue": queue,
            "reply_to": reply_topic,
        })

        return {
            "status": "pending_hil",
            "correlation_id": correlation_id,
            "reply_to": reply_topic,
            "message": "Human review triggered, check back later",
        }
