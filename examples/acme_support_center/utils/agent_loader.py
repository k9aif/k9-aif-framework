# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — acme_support_center SBB

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

log = logging.getLogger(__name__)


class AgentLoader:
    """
    Loads per-agent YAML files from a directory and provides merged configs
    for agent construction.

    Each YAML file must contain a ``class:`` field that maps to the Python
    class name (e.g., ``class: KnowledgeAgent``).

    Usage::

        loader = AgentLoader(Path("agents/yaml"))
        config = loader.merge_with_global("KnowledgeAgent", global_config)
        agent  = KnowledgeAgent(config=config)

    Merge strategy: global_config supplies infrastructure (``inference``,
    ``runtime``, ``router``, …); agent YAML supplies behavior (``role``,
    ``goal``, ``pattern``, ``model``, ``instructions``, ``config``, …).
    When both sides define the same top-level key, the agent YAML wins.
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
        Return a merged config dict.

        global_config is the base (infrastructure: inference, runtime, router …).
        Agent YAML fields are layered on top and win on key collision.
        If no YAML is found for class_name, global_config is returned unchanged.
        """
        agent_yaml = self._by_class.get(class_name, {})
        return {**global_config, **agent_yaml}

    def has_agent(self, class_name: str) -> bool:
        return class_name in self._by_class

    def list_classes(self) -> List[str]:
        return list(self._by_class.keys())
