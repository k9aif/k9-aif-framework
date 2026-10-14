# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — CustomerServiceOrchestrator (SBB)
#
# Subscribes to: eoc-customer
# Squad: CustomerServiceSquad — agent pipeline defined in config/squads.yaml

import logging
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus

log = logging.getLogger(__name__)

_SQUAD_ID = "CustomerServiceSquad"
_TOPIC    = "eoc-customer"

class CustomerServiceOrchestrator(BaseOrchestrator):
    """
    SBB Orchestrator for CustomerServiceSquad.

    Subscribes to ``eoc-customer``. On startup, uses SquadLoader to build
    the squad from config/squads.yaml and instantiate all required agents.
    Agent execution order and escalation conditions are fully declared in
    the YAML ``flow:`` section.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, squads=None, **kwargs) -> None:
        cfg = config or {}
        zt_enabled = cfg.get("governance", {}).get("enabled", False)
        super().__init__(config=cfg, enable_zero_trust=zt_enabled)
        if squads is None:
            from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.squad_layer import squad_layer
            squads = squad_layer(cfg)
        self.squads = squads   # the squad layer: squads by YAML file and id, never agents
        self._squad = None
        self._event_bus: Optional[K9EventBus] = None

    # ------------------------------------------------------------------
    def start(self, squads_yaml_path: str) -> None:
        self._squad = self._load_squad(squads_yaml_path)

        messaging = self.config.get("messaging", {})
        brokers = messaging.get("brokers", ["localhost:9092"])
        broker = brokers[0] if isinstance(brokers, list) else brokers

        self._event_bus = K9EventBus(broker_url=broker, topic=_TOPIC, group_id="eoc-customer-grp")
        log.info("[CustomerServiceOrchestrator] Listening on topic: %s", _TOPIC)
        self._event_bus.subscribe(self.handle_event)

    # ------------------------------------------------------------------
    def _load_squad(self, squads_yaml_path: str):
        squad = self.squads.load_one(squads_yaml_path, _SQUAD_ID)
        log.info("[CustomerServiceOrchestrator] Squad loaded: squad_id=%s agents=%d flow_steps=%d",
                 _SQUAD_ID, len(squad.agents), len(squad.flow))
        return squad

    # ------------------------------------------------------------------
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_id = payload.get("event_id", "")
        log.info("[CustomerServiceOrchestrator] Processing customer interaction: event=%s", event_id)
        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            log.warning("[CustomerServiceOrchestrator] Zero Trust DENIED event=%s reason=%s", event_id, zt["reason"])
            return {"status": "denied", "event_id": event_id, "squad_id": _SQUAD_ID, "reason": zt["reason"]}
        normalized = {
            **zt["payload"],
            "claim_id":       payload.get("claim_id") or payload.get("interaction_id", event_id),
            "claimant_id":    payload.get("claimant_id") or payload.get("customer_id", ""),
            "claim_type":     payload.get("claim_type") or payload.get("interaction_type", "inquiry"),
            "notes":          payload.get("notes") or payload.get("customer_message", ""),
            "amount_claimed": payload.get("amount_claimed", 0),
        }
        return self._squad.execute(normalized)
