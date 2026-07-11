# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
AgentLoader — ABB utility for loading per-agent YAML configurations.

Loads agent YAML files from a directory, indexes them by class name, and
produces merged configs for agent construction via ``merge_with_global()``.

Merge strategy
--------------
``global_config`` supplies infrastructure concerns (``inference``, ``messaging``,
``postgres``, ``neo4j``, ``governance``, …).  Agent YAML supplies behavioral
concerns (``role``, ``goal``, ``pattern``, ``model``, ``instructions``,
``governance.pre_process``, …).  When both sides define the same top-level key,
the agent YAML wins — **unless** the key is listed in ``_policy.locked`` inside
``global_config``, in which case the global value is preserved and an audit
warning is logged.

Enterprise policy enforcement
------------------------------
Add a ``_policy`` block to the ABB ``config.yaml`` to lock settings that SBBs
must not override::

    _policy:
      locked:
        - enable_zero_trust
        - security.shield.enabled
        - governance.enforce

Locked keys use dot-notation for nested paths.  The ``_policy`` block itself
is always stripped from the merged result so agents never see it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dot-notation helpers for nested config keys
# ---------------------------------------------------------------------------

def _get_nested(d: Dict, dot_path: str) -> Any:
    """Return the value at ``dot_path`` inside ``d``, or ``None`` if absent."""
    for key in dot_path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _set_nested(d: Dict, dot_path: str, value: Any) -> None:
    """Set the value at ``dot_path`` inside ``d``, creating intermediate dicts."""
    keys = dot_path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


# ---------------------------------------------------------------------------

class AgentLoader:
    """
    Loads per-agent YAML files from a directory and provides merged configs
    for agent construction.

    Each YAML file must contain a ``class:`` field that matches the Python
    class name exactly (e.g. ``class: ClaimsTriageAgent``).

    Usage inside an orchestrator's ``_load_squad()``::

        from k9_aif_abb.k9_agents.agent_loader import AgentLoader

        agents_yaml_dir = Path(__file__).parent.parent / "agents" / "yaml"
        agent_loader = AgentLoader(agents_yaml_dir)

        agent_registry.register(
            "ClaimsTriageAgent",
            lambda: ClaimsTriageAgent(
                config=agent_loader.merge_with_global("ClaimsTriageAgent", self.config)
            ),
        )

    Parallel to ``SquadLoader`` in ``k9_aif_abb/k9_squad/squad_loader.py``.
    """

    def __init__(self, yaml_dir: str | Path) -> None:
        self.yaml_dir = Path(yaml_dir)
        self._by_class: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    # ------------------------------------------------------------------
    def _load_all(self) -> None:
        if not self.yaml_dir.exists():
            log.warning("AgentLoader: yaml_dir not found: %s", self.yaml_dir)
            return
        for path in sorted(self.yaml_dir.glob("*.yaml")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                class_name = (data.get("class") or "").strip()
                if class_name:
                    self._by_class[class_name] = data
                    log.debug("AgentLoader: indexed %s from %s", class_name, path.name)
                else:
                    log.warning("AgentLoader: no 'class' field in %s — skipped", path.name)
            except Exception as exc:
                log.warning("AgentLoader: could not load %s: %s", path, exc)

    # ------------------------------------------------------------------
    def get_agent_yaml(self, class_name: str) -> Optional[Dict[str, Any]]:
        """Return the raw YAML dict for the given agent class name, or None."""
        return self._by_class.get(class_name)

    def merge_with_global(
        self, class_name: str, global_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Return a merged config dict for the named agent class.

        Agent YAML wins on key collision, except for keys listed in
        ``global_config["_policy"]["locked"]`` — those are always restored
        from ``global_config`` and an audit warning is logged when an SBB
        attempted to override them.

        The ``_policy`` block is stripped from the returned dict so agents
        never see it.
        """
        agent_yaml = self._by_class.get(class_name, {})
        merged = {**global_config, **agent_yaml}

        # Enforce enterprise policy locks
        locked: List[str] = global_config.get("_policy", {}).get("locked", [])
        for key_path in locked:
            global_val = _get_nested(global_config, key_path)
            merged_val = _get_nested(merged, key_path)
            if merged_val != global_val:
                log.warning(
                    "AgentLoader: [POLICY] locked key '%s' override rejected for %s "
                    "(attempted value: %r, enforced value: %r)",
                    key_path, class_name, merged_val, global_val,
                )
                _set_nested(merged, key_path, global_val)

        # Strip _policy — agents must not see framework internals
        merged.pop("_policy", None)

        return merged

    def has_agent(self, class_name: str) -> bool:
        """Return True if a YAML file was found for the given class name."""
        return class_name in self._by_class

    def list_classes(self) -> List[str]:
        """Return all indexed agent class names."""
        return list(self._by_class.keys())
