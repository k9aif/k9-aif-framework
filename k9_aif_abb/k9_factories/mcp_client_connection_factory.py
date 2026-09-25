# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/mcp_client_connection_factory.py

from typing import Dict, Type, Any
from threading import Lock
import logging

class MCPClientConnectionFactory:
    """Static Factory - provisions Model Context Protocol (MCP) client connectors."""

    _registry: Dict[str, Type[Any]] = {}
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
        return cls(**kwargs)

    @staticmethod
    def bootstrap() -> None:
        """Register the built-in transports. Never overrides a name already registered by a solution."""
        if MCPClientConnectionFactory._bootstrapped:
            return
        from k9_aif_abb.k9_core.integration.mcp_http_connector import MCPHttpConnector
        from k9_aif_abb.k9_core.integration.mcp_stdio_connector import MCPStdioConnector
        from k9_aif_abb.k9_core.integration.mcp_streamable_http_connector import MCPStreamableHttpConnector

        builtins = {
            "streamable_http": MCPStreamableHttpConnector,  # standard MCP over HTTP (hosted servers)
            "http": MCPHttpConnector,                       # REST convention: /tools, /tools/call
            "stdio": MCPStdioConnector,                     # spawn a local MCP server process
        }
        with MCPClientConnectionFactory._lock:
            for name, conn_cls in builtins.items():
                MCPClientConnectionFactory._registry.setdefault(name, conn_cls)
            MCPClientConnectionFactory._bootstrapped = True
        MCPClientConnectionFactory.logger.info("[Factory] Bootstrapped MCPClientConnectionFactory")