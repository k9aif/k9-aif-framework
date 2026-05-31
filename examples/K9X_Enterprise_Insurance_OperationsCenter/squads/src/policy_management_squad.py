# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — PolicyManagementSquad (SBB)

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from k9_aif_abb.k9_squad.base_squad import BaseSquad

log = logging.getLogger(__name__)


class PolicyManagementSquad(BaseSquad):
    """
    SBB Squad for PolicyManagementSquad.

    Agent pipeline and flow are declared in config/squads.yaml.
    Orchestrators load this squad via SquadLoader — not by instantiating
    this class directly. This SBB exists for registry and type-checking purposes.
    """

    def __init__(
        self,
        name: str,
        agents: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(squad_id=name, agents=[])
        self.name = name
        self.agents = agents
        self.config = config or {}
        log.info("Initialized squad: %s", self.name)
