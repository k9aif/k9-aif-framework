# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Common base for ACME's domain orchestrators: run a squad by its id.

An orchestrator knows only squads (three-layer decoupling, K9-DEC-002): the
squad file and id. Which agents a squad runs is in ``config/squads.yaml``; the
squad layer that builds them (``SquadLoader.from_agents``) is created once in
``app_backend.py`` and passed down as ``squads=``.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

SQUADS_YAML = Path(__file__).resolve().parent.parent / "config" / "squads.yaml"


class AcmeDomainOrchestrator(BaseOrchestrator):
    """BaseOrchestrator plus ``run_squad()``; ACME's domain orchestrators extend it."""

    async def run_squad(self, squad_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Load ``squad_id`` from config/squads.yaml and run it; failures propagate to the caller."""
        if self.squads is None:
            raise RuntimeError(f"{type(self).__name__} needs squads= (SquadLoader.from_agents at the entry point)")
        squad = self.squads.load_one(SQUADS_YAML, squad_id)
        # BaseSquad is sync (it runs async agents itself); keep the event loop free while it works.
        return await asyncio.to_thread(squad.execute, payload)
