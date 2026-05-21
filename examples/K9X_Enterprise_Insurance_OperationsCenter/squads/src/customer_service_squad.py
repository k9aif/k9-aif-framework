# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — CustomerServiceSquad (SBB)

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from k9_aif_abb.k9_squad.base_squad import BaseSquad

log = logging.getLogger(__name__)


class CustomerServiceSquad(BaseSquad):
    """
    SBB Squad for CustomerServiceSquad.

    Extends ``BaseSquad``. Agent pipeline and conditional steps are declared
    in config/squads.yaml ``flow:`` section. This SBB's ``run()`` delegates
    to the orchestrator for backward compatibility.
    """

    def __init__(
        self,
        name: str,
        agents: Dict[str, Any],
        orchestrator: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(squad_id=name, agents=[], orchestrator=orchestrator)
        self.name = name
        self.agents = agents
        self.config = config or {}
        log.info("Initialized squad: %s", self.name)

    def run(self, request: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Delegate to CustomerServiceOrchestrator."""
        context = context or {}
        log.info("Squad %s received request", self.name)
        return self.orchestrator.run(request=request, agents=self.agents, context=context)
