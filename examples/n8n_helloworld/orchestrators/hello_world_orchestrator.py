# SPDX-License-Identifier: Apache-2.0
# K9-AIF n8n Hello World — HelloWorldOrchestrator (SBB)

from __future__ import annotations

import os
from typing import Any, Dict, Optional
import logging

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry

from agents.src.hello_world_agent import HelloWorldAgent

log = logging.getLogger(__name__)

_SQUAD_ID    = "HelloWorldSquad"
_SQUADS_YAML = os.path.join(os.path.dirname(__file__), "../config/squads.yaml")


class HelloWorldOrchestrator(BaseOrchestrator):

    layer = "n8n_helloworld HelloWorldOrchestrator SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.squad = self._load_squad()

    def _load_squad(self):
        registry = AgentRegistry()
        registry.register(
            "HelloWorldAgent",
            lambda: HelloWorldAgent(config=self.config),
        )
        loader = SquadLoader(registry)
        return loader.load_one(_SQUADS_YAML, _SQUAD_ID)

    def run(self, event: Dict[str, Any]) -> Dict[str, Any]:
        log.info("[%s] Running squad for event: %s", self.layer, event)
        result = self.squad.run(dict(event))
        self.publish_event({"type": "HelloWorldFlowCompleted", "result": result.get("hello", {})})
        return result
