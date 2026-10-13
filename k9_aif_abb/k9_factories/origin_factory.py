# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
OriginFactory — builds k9x Origin from a solution's configuration.

``config/config.yaml``::

    origin:
      enabled: true
      config: config/origin.yaml        # entities, sources, topics, squads, agents
      state: { provider: in_memory }    # in_memory | redis (shared, LRU-bounded)

Governance comes from ``origin.yaml``'s ``governance.request_checks`` / ``answer_checks``
(k9x Shield check names) on top of the solution's ``security.shield``; production refuses an
ungoverned Origin, as it refuses ungoverned agents and event gates.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Optional

log = logging.getLogger("OriginFactory")


class OriginFactory:
    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("OriginFactory is static and cannot be instantiated")

    @staticmethod
    def create(config: Optional[Dict[str, Any]] = None, projections: Optional[Iterable[Any]] = None,
               state: Any = None, base_dir: Optional[str] = None):
        """A K9Origin for this solution, or None when ``origin.enabled`` is not true."""
        from k9_aif_abb.k9_origin.config import OriginConfig
        from k9_aif_abb.k9_origin.origin import K9Origin

        cfg = config or {}
        ocfg = cfg.get("origin") or {}
        if not ocfg.get("enabled"):
            return None
        path = ocfg.get("config")
        if path:
            if base_dir and not os.path.isabs(path):
                path = os.path.join(base_dir, path)
            policy = OriginConfig.load(path)
        else:
            policy = OriginConfig.from_dict(ocfg.get("policy") or {})

        if state is None:
            state = OriginFactory._state(cfg, ocfg, projections)
        request_gov, answer_gov = OriginFactory._governance(cfg, policy)
        return K9Origin(state, policy, request_governance=request_gov, answer_governance=answer_gov)

    @staticmethod
    def _state(cfg: Dict[str, Any], ocfg: Dict[str, Any], projections):
        from k9_aif_abb.k9_factories.streams_factory import StreamsFactory
        provider = str((ocfg.get("state") or {}).get("provider", "in_memory")).lower()
        merged = {**cfg, "streams": {**(cfg.get("streams") or {}), "enabled": True,
                                     "state": {**((cfg.get("streams") or {}).get("state") or {}),
                                               **(ocfg.get("state") or {}), "provider": provider}}}
        return StreamsFactory.create_state(merged, projections=projections)

    @staticmethod
    def _governance(cfg: Dict[str, Any], policy):
        from k9_aif_abb.k9_core.governance.pipeline import is_permissive_env
        from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance

        g = policy.governance or {}
        request = g.get("request_checks", ["PromptInjectionCheck", "PIIRequestCheck"])
        answer = g.get("answer_checks", ["PromptInjectionCheck"])
        shield = ((cfg.get("security") or {}).get("shield") or {})
        shielded = bool(shield.get("enabled", False)) or bool(g)
        if not shielded:
            if is_permissive_env(cfg.get("k9_env")):
                log.warning("[OriginFactory] k9x Origin runs WITHOUT Shield (K9_ENV allows it)")
                return None, None
            raise PermissionError("k9x Origin must be governed outside development/test: enable "
                                  "security.shield or set governance checks in origin.yaml")
        check_config = shield.get("check_config") or {}

        def build(checks):
            return ShieldGovernance({"security": {"shield": {"enabled": True, "ingress": {"checks": list(checks)},
                                                             "check_config": check_config}}}) if checks else None
        return build(request), build(answer)
