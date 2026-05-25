# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — EOCOrchestrator (SBB)
#
# Synchronous HTTP adapter that loads all seven squad orchestrators and
# dispatches incoming events directly to the correct squad — no Kafka in
# the loop. Used by the FastAPI layer (api/app.py) so the UI can work
# without a running message broker.
#
# Full hierarchy (HTTP mode):
#   app.py → EOCOrchestrator.execute_flow() → squad.handle_event() → agents
#
# Full hierarchy (Kafka / production mode):
#   EOCRouter → Kafka topic → orchestrator.start() → squad → agents

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import yaml as _yaml

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.claims_processing_orchestrator import ClaimsProcessingOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.document_intelligence_orchestrator import DocumentIntelligenceOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.risk_assessment_orchestrator import RiskAssessmentOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.policy_management_orchestrator import PolicyManagementOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.catastrophe_response_orchestrator import CatastropheResponseOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.customer_service_orchestrator import CustomerServiceOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.audit_compliance_orchestrator import AuditComplianceOrchestrator

# Re-export EOCRouter for any existing imports.
from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router import EOCRouter

__all__ = ["EOCOrchestrator", "EOCRouter"]

log = logging.getLogger(__name__)

_SQUADS_YAML = Path(__file__).parent.parent / "config" / "squads.yaml"

# Maps event_type → orchestrator class
_ROUTING: Dict[str, type] = {
    "claim_submitted":             ClaimsProcessingOrchestrator,
    "document_received":           DocumentIntelligenceOrchestrator,
    "fraud_signal_raised":         RiskAssessmentOrchestrator,
    "policy_change_requested":     PolicyManagementOrchestrator,
    "catastrophe_alert_issued":    CatastropheResponseOrchestrator,
    "customer_interaction_logged": CustomerServiceOrchestrator,
    "audit_query_received":        AuditComplianceOrchestrator,
}

# Maps orchestrator class name → squad ID in squads.yaml.
# Defined here (not in squad YAML) — squads do not reference their callers.
_SQUAD_MAP: Dict[str, str] = {
    "ClaimsProcessingOrchestrator":     "ClaimsProcessingSquad",
    "DocumentIntelligenceOrchestrator": "DocumentIntelligenceSquad",
    "RiskAssessmentOrchestrator":       "RiskAssessmentSquad",
    "PolicyManagementOrchestrator":     "PolicyManagementSquad",
    "CatastropheResponseOrchestrator":  "CatastropheResponseSquad",
    "CustomerServiceOrchestrator":      "CustomerServiceSquad",
    "AuditComplianceOrchestrator":      "AuditComplianceSquad",
}


class EOCOrchestrator(BaseOrchestrator):
    """
    HTTP-mode orchestrator for the K9X EOC API.

    Extends ``BaseOrchestrator`` so zero trust fires before every dispatch.
    Instantiates all seven squad orchestrators at startup, loads their
    agent squads directly (skipping Kafka), and exposes ``execute_flow``
    so the FastAPI layer can dispatch events synchronously.

    Usage::

        orchestrator = EOCOrchestrator(config=config)
        result = await orchestrator.execute_flow(payload)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        zt_enabled = cfg.get("governance", {}).get("enabled", False)
        super().__init__(config=cfg, enable_zero_trust=zt_enabled)
        self._handlers: Dict[str, Any] = {}
        self._initialize()

    # ------------------------------------------------------------------
    def _initialize(self) -> None:
        # Load the combined squads.yaml and split it into per-orchestrator
        # temp files so SquadLoader only sees one squad at a time.
        # (SquadLoader.load() instantiates every squad in the file — if an
        # orchestrator's registry only covers its own agents the other squads
        # would fail to build.)
        with open(_SQUADS_YAML) as f:
            all_squads_data = _yaml.safe_load(f) or {}
        all_squads = all_squads_data.get("squads", {})

        log.info("[EOCOrchestrator] Startup: %d event types to load", len(_ROUTING))
        for event_type, cls in _ROUTING.items():
            tmp_path: Optional[str] = None
            try:
                orch = cls(config=self.config)
                log.info("[EOCOrchestrator] Orchestrator ready: %s → event_type=%s", cls.__name__, event_type)

                squad_id = _SQUAD_MAP.get(cls.__name__)
                squad_cfg = all_squads.get(squad_id) if squad_id else None
                if not squad_id or squad_cfg is None:
                    raise ValueError(f"No squad found in squads.yaml for {cls.__name__}")

                # Write a single-squad YAML so SquadLoader only builds this squad
                per_squad = {"squads": {squad_id: squad_cfg}}
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False,
                    dir=_SQUADS_YAML.parent,
                ) as tf:
                    _yaml.dump(per_squad, tf)
                    tmp_path = tf.name

                orch._squad = orch._load_squad(tmp_path)
                orch._agent_map = {a.__class__.__name__: a for a in orch._squad.agents}
                self._handlers[event_type] = orch
                log.info(
                    "[EOCOrchestrator] Squad loaded: event_type=%s squad=%s agents=%d flow_steps=%d",
                    event_type, squad_id, len(orch._squad.agents), len(orch._squad.flow),
                )
            except Exception:
                log.exception("[EOCOrchestrator] Failed loading squad for event_type=%s", event_type)
                raise
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        log.info("[EOCOrchestrator] Startup complete: %d handlers registered", len(self._handlers))

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch an event to the correct squad orchestrator and return
        the result. Runs the (synchronous) ``handle_event`` in a thread
        executor so the FastAPI event loop is not blocked.

        Args:
            payload: Full event dict — must include ``event_type``.

        Returns:
            Squad result dict (status, decision, audit trail, etc.).
        """
        event_type = payload.get("event_type", payload.get("intent", "")).lower().strip()
        handler = self._handlers.get(event_type)

        if handler is None:
            log.warning("[EOCOrchestrator] No handler for event_type=%r", event_type)
            return {
                "status": "error",
                "event_type": event_type,
                "detail": f"No squad orchestrator registered for event_type '{event_type}'.",
                "supported": list(_ROUTING.keys()),
            }

        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            log.warning(
                "[EOCOrchestrator] Zero Trust DENIED event_type=%s reason=%s risk=%s",
                event_type, zt["reason"], zt["risk_score"],
            )
            return {"status": "denied", "event_type": event_type, "reason": zt["reason"]}

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, handler.execute_flow, zt["payload"])
        except Exception:
            log.exception("[EOCOrchestrator] Pipeline FAILED event_type=%s", event_type)
            raise
