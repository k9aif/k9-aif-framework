# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_factories/agent_factory.py

import logging
from threading import Lock
from typing import Any, Dict, Type

class AgentFactory:
    """
    K9-AIF Factory - AgentFactory
    -----------------------------
    Static factory for provisioning core ABB agents.
    Ensures consistent registration, lookup, and instantiation.
    """

    _registry: Dict[str, Type[Any]] = {}
    _bootstrapped: bool = False
    _lock = Lock()
    logger = logging.getLogger("AgentFactory")

    def __init__(self, *args, **kwargs):
        raise RuntimeError("AgentFactory is static and cannot be instantiated")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def bootstrap() -> None:
        """
        Bootstraps the default agent registry.
        Lazy-loads agents to prevent circular imports.
        """
        with AgentFactory._lock:
            if AgentFactory._bootstrapped:
                return

            try:
                from k9_aif_abb.k9_agents.security.auth_agent import AuthAgent
                AgentFactory._registry["auth"] = AuthAgent
            except Exception as e:
                AgentFactory.logger.warning(f"[Factory] [WARN] AuthAgent not available: {e}")

            try:
                from k9_aif_abb.k9_agents.enrichment.enrichment_agent import EnrichmentAgent
                AgentFactory._registry["enrichment"] = EnrichmentAgent
            except Exception as e:
                AgentFactory.logger.warning(f"[Factory] [WARN] EnrichmentAgent not available: {e}")

            AgentFactory._bootstrapped = True
            AgentFactory.logger.info("[Factory] Bootstrapped AgentFactory (lazy, circular-safe)")

    # ------------------------------------------------------------------
    @staticmethod
    def register(name: str, cls: Type[Any]) -> None:
        """Registers a custom agent at runtime."""
        with AgentFactory._lock:
            AgentFactory._registry[name.lower()] = cls
            AgentFactory.logger.debug(f"[Factory] Registered Agent '{name}' -> {cls.__name__}")

    # ------------------------------------------------------------------
    @staticmethod
    def get(name: str) -> Type[Any]:
        """Returns the agent class without instantiating it."""
        try:
            return AgentFactory._registry[name.lower()]
        except KeyError:
            raise ValueError(f"No agent registered under name '{name}'")

    # ------------------------------------------------------------------
    @staticmethod
    def create(name: str, **kwargs: Any):
        """Instantiates an agent by name."""
        if not AgentFactory._bootstrapped:
            AgentFactory.bootstrap()
        try:
            cls = AgentFactory._registry[name.lower()]
            return cls(**kwargs)
        except KeyError:
            raise ValueError(f"No agent registered under name '{name}'")