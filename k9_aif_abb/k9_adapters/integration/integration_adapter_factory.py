# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
IntegrationAdapterFactory — registry + factory for K9-AIF integration adapters.

SBBs register themselves; the factory resolves by adapter_type string.
Follows the same static-factory pattern as CacheFactory, ObjectStorageFactory.

Usage:
    IntegrationAdapterFactory.register("my_api", MyApiAdapter)
    adapter = IntegrationAdapterFactory.create("my_api", config={"url": "..."})
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Dict, Optional, Type

from .base_integration_adapter import BaseIntegrationAdapter

_ADAPTER_TYPE_MAP: Dict[str, str] = {
    "api_adapter":          "api",
    "messaging_adapter":    "messaging",
    "rules_adapter":        "rules",
    "workflow_adapter":     "workflow",
    "process_adapter":      "process_flow",
    "bpm_adapter":          "bpm",
    "data_adapter":         "data",
}


class IntegrationAdapterFactory:
    """Static factory for integration adapters. Thread-safe registry."""

    _registry: Dict[str, Type[BaseIntegrationAdapter]] = {}
    _lock: Lock = Lock()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("IntegrationAdapterFactory is static — do not instantiate")

    @staticmethod
    def register(name: str, cls: Type[BaseIntegrationAdapter]) -> None:
        """Register a concrete adapter SBB under a name."""
        with IntegrationAdapterFactory._lock:
            IntegrationAdapterFactory._registry[name.lower()] = cls

    @staticmethod
    def get(name: str, config: Optional[Dict[str, Any]] = None) -> BaseIntegrationAdapter:
        """Return an instance of the named adapter. Raises ValueError if unknown."""
        key = _ADAPTER_TYPE_MAP.get(name.lower(), name.lower())
        cls = IntegrationAdapterFactory._registry.get(key)
        if cls is None:
            available = list(IntegrationAdapterFactory._registry.keys())
            raise ValueError(
                f"No adapter registered for '{name}'. "
                f"Register an SBB first. Available: {available}"
            )
        return cls(config=config or {})

    @staticmethod
    def create(adapter_type: str, config: Optional[Dict[str, Any]] = None) -> BaseIntegrationAdapter:
        """Alias for get() — matches the factory convention used elsewhere in K9-AIF."""
        return IntegrationAdapterFactory.get(adapter_type, config=config)

    @staticmethod
    def registered() -> list:
        """Return list of registered adapter type names."""
        return list(IntegrationAdapterFactory._registry.keys())
