# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — the squad layer
"""The EOC squad layer: squads are YAML (``config/squads.yaml``), ``BaseSquad`` runs them.

An orchestrator knows only squads (three-layer decoupling, k9_inspect K9-DEC-002): it
loads a squad by YAML file and squad id through the loader built here. The agents a
squad needs are named in its YAML and built by this loader, never by an orchestrator.
If a squad's agents change, no orchestrator changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from k9_aif_abb.k9_squad.squad_loader import SquadLoader

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents" / "yaml"


def squad_layer(config: Dict[str, Any]) -> SquadLoader:
    """The squad layer for every EOC orchestrator (built once, at the entry point)."""
    return SquadLoader.from_agents(AGENTS_DIR, config=config)
