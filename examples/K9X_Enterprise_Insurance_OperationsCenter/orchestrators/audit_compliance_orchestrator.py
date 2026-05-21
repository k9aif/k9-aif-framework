# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — AuditComplianceOrchestrator (SBB)
#
# Subscribes to: eoc-audit
# Squad: AuditComplianceSquad — agent pipeline defined in config/squads.yaml

import logging
from typing import Any, Dict, Optional

from pathlib import Path

from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_orchestrators.registry.orchestrator_registry import OrchestratorRegistry
from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus

from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.agent_loader import AgentLoader
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.audit_agent import AuditAgent

log = logging.getLogger(__name__)

_SQUAD_ID = "AuditComplianceSquad"
_TOPIC    = "eoc-audit"


class AuditComplianceOrchestrator(BaseOrchestrator):
    """
    SBB Orchestrator for AuditComplianceSquad.

    Extends ``BaseOrchestrator`` so zero trust fires before every squad execution.
    Subscribes to ``eoc-audit``. Agent execution order is fully declared in
    the YAML ``flow:`` section.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        cfg = config or {}
        zt_enabled = cfg.get("governance", {}).get("enabled", False)
        super().__init__(config=cfg, enable_zero_trust=zt_enabled)
        self._squad = None
        self._agent_map: Dict[str, Any] = {}
        self._event_bus: Optional[K9EventBus] = None

    # ------------------------------------------------------------------
    def start(self, squads_yaml_path: str) -> None:
        self._squad = self._load_squad(squads_yaml_path)
        self._agent_map = {a.__class__.__name__: a for a in self._squad.agents}

        messaging = self.config.get("messaging", {})
        brokers = messaging.get("brokers", ["localhost:9092"])
        broker = brokers[0] if isinstance(brokers, list) else brokers

        self._event_bus = K9EventBus(broker_url=broker, topic=_TOPIC, group_id="eoc-audit-grp")
        log.info("[AuditComplianceOrchestrator] Listening on topic: %s", _TOPIC)
        self._event_bus.subscribe(self.handle_event)

    # ------------------------------------------------------------------
    def _load_squad(self, squads_yaml_path: str):
        agents_yaml_dir = Path(squads_yaml_path).parent.parent / "agents" / "yaml"
        agent_loader = AgentLoader(agents_yaml_dir)

        agent_registry = AgentRegistry()
        agent_registry.register(
            "AuditAgent",
            lambda: AuditAgent(config=agent_loader.merge_with_global("AuditAgent", self.config)),
        )

        orchestrator_registry = OrchestratorRegistry()
        orchestrator_registry.register("AuditComplianceOrchestrator", AuditComplianceOrchestrator)

        loader = SquadLoader(agent_registry, orchestrator_registry)
        squad = loader.load_one(squads_yaml_path, _SQUAD_ID)
        log.info("[AuditComplianceOrchestrator] Squad loaded: squad_id=%s agents=%d flow_steps=%d",
                 _SQUAD_ID, len(squad.agents), len(squad.flow))
        return squad

    # ------------------------------------------------------------------
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_id       = payload.get("event_id", "")
        correlation_id = payload.get("correlation_id", "")
        log.info("[AuditComplianceOrchestrator] Processing audit query: event=%s", event_id)
        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            log.warning("[AuditComplianceOrchestrator] Zero Trust DENIED event=%s reason=%s", event_id, zt["reason"])
            return {"status": "denied", "event_id": event_id, "squad_id": _SQUAD_ID, "reason": zt["reason"]}
        normalized = {
            **zt["payload"],
            "correlation_id": payload.get("query_correlation_id") or correlation_id,
            "event_id":       payload.get("query_event_id") or event_id,
            "agent_name":     payload.get("query_agent_name"),
            "event_type":     payload.get("query_event_type"),
        }
        result = self._squad.execute(normalized)
        entries = result.get("query_result", {}).get("entries", [])
        log.info("[AuditComplianceOrchestrator] Report: %d entries | correlation=%s", len(entries), correlation_id)
        result["audit_entries"]     = entries
        result["entry_count"]       = len(entries)
        result["compliance_report"] = self._assemble_report(entries, payload)
        return result

    # ------------------------------------------------------------------
    def _assemble_report(self, entries: list, query: Dict[str, Any]) -> Dict[str, Any]:
        if not entries:
            return {"summary": "No audit entries found for the specified filters", "entries": []}

        agents_involved = list({e.get("agent_name") for e in entries if e.get("agent_name")})
        event_types     = list({e.get("event_type") for e in entries if e.get("event_type")})
        decisions       = [e.get("disposition") for e in entries if e.get("disposition")]
        avg_confidence  = (
            sum(e.get("confidence_score", 0) for e in entries) / len(entries) if entries else 0.0
        )

        return {
            "total_entries":    len(entries),
            "agents_involved":  agents_involved,
            "event_types":      event_types,
            "decisions":        decisions,
            "average_confidence": round(avg_confidence, 3),
            "earliest_entry":   entries[-1].get("timestamp_utc") if entries else None,
            "latest_entry":     entries[0].get("timestamp_utc") if entries else None,
            "query_filters":    {k: v for k, v in query.items() if k.startswith("query_")},
        }
