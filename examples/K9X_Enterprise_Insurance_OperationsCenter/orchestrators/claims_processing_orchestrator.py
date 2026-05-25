# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — ClaimsProcessingOrchestrator (SBB)
#
# Subscribes to: eoc-claims
# Squad:  ClaimsProcessingSquad — agent pipeline defined in config/squads.yaml

import logging
from typing import Any, Dict, Optional

from pathlib import Path

from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus

from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.agent_loader import AgentLoader
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import ClaimsTriageAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.adjudication_agent import AdjudicationAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.guard_agent import GuardAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.audit_agent import AuditAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.escalation_agent import EscalationAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.graph_sync_agent import GraphSyncAgent

log = logging.getLogger(__name__)

_SQUAD_ID = "ClaimsProcessingSquad"
_TOPIC    = "eoc-claims"

class ClaimsProcessingOrchestrator(BaseOrchestrator):
    """
    SBB Orchestrator for ClaimsProcessingSquad.

    Extends ``BaseOrchestrator`` so zero trust fires before every squad execution.
    Subscribes to ``eoc-claims``. Agent execution order and conditional steps are
    fully declared in the YAML ``flow:`` section — no hardcoded chain in this class.
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
        """
        Bootstrap and begin listening.

        Args:
            squads_yaml_path: Absolute path to ``config/squads.yaml``.
        """
        self._squad = self._load_squad(squads_yaml_path)
        self._agent_map = {a.__class__.__name__: a for a in self._squad.agents}

        messaging = self.config.get("messaging", {})
        brokers = messaging.get("brokers", ["localhost:9092"])
        broker = brokers[0] if isinstance(brokers, list) else brokers

        self._event_bus = K9EventBus(broker_url=broker, topic=_TOPIC, group_id="eoc-claims-grp")
        log.info("[ClaimsProcessingOrchestrator] Listening on topic: %s", _TOPIC)
        self._event_bus.subscribe(self.handle_event)

    # ------------------------------------------------------------------
    def _load_squad(self, squads_yaml_path: str):
        agents_yaml_dir = Path(squads_yaml_path).parent.parent / "agents" / "yaml"
        agent_loader = AgentLoader(agents_yaml_dir)

        agent_registry = AgentRegistry()
        for name, cls in [
            ("ClaimsTriageAgent",  ClaimsTriageAgent),
            ("AdjudicationAgent",  AdjudicationAgent),
            ("GuardAgent",         GuardAgent),
            ("AuditAgent",         AuditAgent),
            ("EscalationAgent",    EscalationAgent),
            ("GraphSyncAgent",     GraphSyncAgent),
        ]:
            agent_registry.register(
                name,
                lambda c=cls, n=name: c(config=agent_loader.merge_with_global(n, self.config)),
            )

        loader = SquadLoader(agent_registry)
        squad = loader.load_one(squads_yaml_path, _SQUAD_ID)
        log.info("[ClaimsProcessingOrchestrator] Squad loaded: squad_id=%s agents=%d flow_steps=%d",
                 _SQUAD_ID, len(squad.agents), len(squad.flow))
        return squad

    # ------------------------------------------------------------------
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_id = payload.get("event_id", "")
        log.info("[ClaimsProcessingOrchestrator] Processing claim: event=%s", event_id)
        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            log.warning("[ClaimsProcessingOrchestrator] Zero Trust DENIED event=%s reason=%s", event_id, zt["reason"])
            return {"status": "denied", "event_id": event_id, "squad_id": _SQUAD_ID, "reason": zt["reason"]}
        return self._squad.execute(zt["payload"])
