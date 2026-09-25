# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/mcp_client_connection_factory.py

from typing import Dict, Type, Any, Union
from threading import Lock
import importlib
import logging

class MCPClientConnectionFactory:
    """Static Factory - provisions Model Context Protocol (MCP) client connectors."""

    _registry: Dict[str, Union[Type[Any], str]] = {}  # class, or "module:Class" resolved on first get()
    _bootstrapped = False
    _lock = Lock()
    logger = logging.getLogger("MCPClientConnectionFactory")

    def __init__(self, *args, **kwargs):
        raise RuntimeError("MCPClientConnectionFactory is static and cannot be instantiated")

    @staticmethod
    def register(name: str, conn_cls: Type[Any]) -> None:
        with MCPClientConnectionFactory._lock:
            MCPClientConnectionFactory._registry[name] = conn_cls
            MCPClientConnectionFactory.logger.debug(f"Registered MCP client '{name}'")

    @staticmethod
    def get(name: str, **kwargs: Any):
        """Instantiate a registered connector, e.g. ``get("streamable_http", config={...})``."""
        MCPClientConnectionFactory.bootstrap()
        cls = MCPClientConnectionFactory._registry.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown MCP client: {name} (registered: {sorted(MCPClientConnectionFactory._registry)})"
            )
        if isinstance(cls, str):
            # Built-ins are registered by import path and resolved on first use,
            # so one transport's optional dependency (e.g. httpx for "http")
            # is only needed when that transport is actually requested.
            module_path, _, class_name = cls.partition(":")
            cls = getattr(importlib.import_module(module_path), class_name)
            with MCPClientConnectionFactory._lock:
                MCPClientConnectionFactory._registry[name] = cls
        return cls(**kwargs)

    @staticmethod
    def bootstrap() -> None:
        """Register the built-in transports. Never overrides a name already registered by a solution."""
        if MCPClientConnectionFactory._bootstrapped:
            return
        integration = "k9_aif_abb.k9_core.integration"
        builtins = {
            # standard MCP over HTTP (hosted servers)
            "streamable_http": f"{integration}.mcp_streamable_http_connector:MCPStreamableHttpConnector",
            # REST convention: /tools, /tools/call
            "http": f"{integration}.mcp_http_connector:MCPHttpConnector",
            # spawn a local MCP server process
            "stdio": f"{integration}.mcp_stdio_connector:MCPStdioConnector",
        }
        with MCPClientConnectionFactory._lock:
            for name, target in builtins.items():
                MCPClientConnectionFactory._registry.setdefault(name, target)
            MCPClientConnectionFactory._bootstrapped = True
        MCPClientConnectionFactory.logger.info("[Factory] Bootstrapped MCPClientConnectionFactory")