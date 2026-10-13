# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""origin.yaml — a solution's entities, sources, squads and agents for k9x Origin."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    """${VAR} / ${VAR:-default} from the environment; addresses and secrets stay in .env."""
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


@dataclass
class ConflictWatch:
    """A watched field. ``transitions`` (e.g. ``approved -> disapproved``) are flagged when they
    happen within ``within_seconds`` of the field's previous change; without transitions, any
    second change within the window is flagged."""

    field: str
    within_seconds: float = 300
    transitions: List[tuple] = field(default_factory=list)


@dataclass
class EntityPolicy:
    name: str
    key: str = "id"
    system_of_record: Optional[str] = None
    owned_fields: List[str] = field(default_factory=list)
    conflicts: List[ConflictWatch] = field(default_factory=list)


@dataclass
class OriginConfig:
    entities: Dict[str, EntityPolicy] = field(default_factory=dict)
    sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    topics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    squads: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    governance: Dict[str, Any] = field(default_factory=dict)

    # ── derived views ──────────────────────────────────────────────────
    def allowed_entities(self, agent: Optional[str]) -> Optional[set]:
        """An agent's scope; None means every declared entity (or anything, if none declared)."""
        if agent and agent in self.agents and self.agents[agent].get("allowed_entities") is not None:
            return {str(e).lower() for e in self.agents[agent]["allowed_entities"]}
        return {e.lower() for e in self.entities} or None

    def verifies(self, agent: Optional[str]) -> bool:
        """True when this agent is a squad step listed in a ``verify_before``."""
        return bool(agent) and any(agent in (s.get("verify_before") or []) for s in self.squads.values())

    def squad_refs(self, squad_id: str) -> List[str]:
        return list((self.squads.get(squad_id) or {}).get("live_context") or [])

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "OriginConfig":
        data = _expand(data or {})
        entities: Dict[str, EntityPolicy] = {}
        for name, spec in (data.get("entities") or {}).items():
            spec = spec or {}
            watches: List[ConflictWatch] = []
            conflicts = spec.get("conflicts") or {}
            for fname, w in conflicts.items():
                w = w or {}
                transitions = []
                for t in w.get("transitions") or []:
                    a, _, b = str(t).partition("->")
                    transitions.append((a.strip(), b.strip()))
                watches.append(ConflictWatch(fname, float(w.get("within_seconds", 300)), transitions))
            entities[name] = EntityPolicy(name=name, key=spec.get("key", "id"),
                                          system_of_record=spec.get("system_of_record"),
                                          owned_fields=list(spec.get("owned_fields") or []),
                                          conflicts=watches)
        return cls(entities=entities, sources=data.get("sources") or {}, topics=data.get("topics") or {},
                   squads=data.get("squads") or {}, agents=data.get("agents") or {},
                   governance=data.get("governance") or {})

    @classmethod
    def load(cls, path: str | Path) -> "OriginConfig":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})
