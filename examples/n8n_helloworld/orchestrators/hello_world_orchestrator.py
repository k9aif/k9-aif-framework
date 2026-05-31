# SPDX-License-Identifier: Apache-2.0
# K9-AIF n8n Hello World — HelloWorldOrchestrator (SBB)

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from typing import Any, Dict, Optional
import logging

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_core.agent.base_agent import AgentRegistry

from examples.n8n_helloworld.agents.src.hello_world_agent import HelloWorldAgent

log = logging.getLogger(__name__)

_SQUAD_ID    = "HelloWorldSquad"
_SQUADS_YAML = os.path.join(os.path.dirname(__file__), "../config/squads.yaml")
_AGENTS_YAML = os.path.join(os.path.dirname(__file__), "../agents/yaml")


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
        context = dict(event)
        result = self.squad.run(context)
        self.publish_event({"type": "HelloWorldFlowCompleted", "result": result.get("hello", {})})
        return result
