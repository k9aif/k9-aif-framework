# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/integration/mcp_streamable_http_connector.py

import datetime
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from k9_aif_abb.k9_core.integration.base_connector import BaseConnector


class MCPToolError(RuntimeError):
    """Raised when an MCP server reports a tool call as failed (``isError``)."""


class MCPStreamableHttpConnector(BaseConnector):
    """
    SBB: MCP client connector over the standard MCP streamable-HTTP transport.

    Speaks the real MCP protocol (JSON-RPC ``initialize`` handshake,
    ``tools/list``, ``tools/call``) to a hosted MCP server, e.g. one built
    with the official SDK's ``FastMCP`` and served at ``http://host:port/mcp``.
    Use this for any deployed, standards-compliant MCP server;
    ``MCPHttpConnector`` only speaks a simpler REST convention
    (``/tools``, ``/tools/call``) and cannot reach such servers.

    Config (keys read from ``kwargs`` first, then the top level)::

        name: mcp-ap-tools
        kwargs:
          url: http://mcp-host:8765/mcp     # or base_url
          api_key: ...                      # optional, sent as Bearer token
          headers: {X-Tenant: acme}         # optional extra headers
          timeout: 30                       # seconds, HTTP operations
          sse_read_timeout: 300             # seconds, streamed responses

    Each call opens its own MCP session and closes it before returning.
    The SDK's transport is built on anyio cancel scopes, which are bound to
    the asyncio task that entered them -- a session opened in ``connect()``
    and closed in ``close()`` breaks as soon as those run in different
    tasks. ``connect()``/``close()`` therefore hold no session.

    Requires the optional ``mcp`` extra: ``pip install "k9-aif[mcp]"``.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        kwargs = config.get("kwargs", {}) or {}

        def opt(key: str, default: Any = None) -> Any:
            return kwargs.get(key, config.get(key, default))

        self.name = config.get("name", "mcp-streamable-http")
        self.url: Optional[str] = opt("url") or opt("base_url")
        if not self.url:
            raise ValueError(f"[{self.name}] MCPStreamableHttpConnector requires 'url' (or 'base_url')")
        self.api_key: Optional[str] = opt("api_key")
        self.headers: Dict[str, str] = dict(opt("headers", {}) or {})
        self.timeout: float = float(opt("timeout", 30))
        self.sse_read_timeout: float = float(opt("sse_read_timeout", 300))

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        getattr(self.logger, level.lower(), self.logger.info)(
            f"{ts} | {self.__class__.__name__:<28} | {msg}"
        )

    # ---------------- session ----------------
    def _request_headers(self) -> Dict[str, str]:
        headers = dict(self.headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        """Open, initialize and yield one MCP client session."""
        try:
            from mcp import ClientSession
            from mcp.client import streamable_http
        except ImportError as exc:
            raise ImportError(
                "MCPStreamableHttpConnector needs the MCP SDK: pip install \"k9-aif[mcp]\""
            ) from exc

        headers = self._request_headers() or None

        if hasattr(streamable_http, "streamable_http_client"):
            # Current SDK: transport takes a pre-built httpx client
            import httpx

            async with streamable_http.create_mcp_http_client(
                headers=headers,
                timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
            ) as http_client:
                async with streamable_http.streamable_http_client(self.url, http_client=http_client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        yield session
        else:
            # Older SDKs (< 1.2x): headers and timeouts passed directly
            async with streamable_http.streamablehttp_client(
                self.url,
                headers=headers,
                timeout=self.timeout,
                sse_read_timeout=self.sse_read_timeout,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session

    # ---------------- public API ----------------
    async def connect(self):
        # No persistent session -- see class docstring
        self.log(f"Using MCP streamable-HTTP server at {self.url}")

    async def list_tools(self) -> Dict[str, Any]:
        """Return the server's ``tools/list`` result: ``{"tools": [{name, description, inputSchema, ...}]}``."""
        async with self._session() as session:
            result = await session.list_tools()
        return _dump(result)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a named tool and return its result as a dict.

        Returns the tool's structured content when the server provides it,
        otherwise the JSON parsed from its text content, otherwise the raw
        content blocks under ``"content"``. Raises ``MCPToolError`` when the
        server marks the call as failed.
        """
        async with self._session() as session:
            result = await session.call_tool(tool_name, arguments or {})
        return _unwrap_tool_result(tool_name, result)

    async def close(self):
        self.log("Closing MCP streamable-HTTP connector (no persistent session)")


def _dump(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True, mode="json")
    return dict(obj)


def _text_of(content: Any) -> str:
    parts = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text is not None:
            parts.append(text)
    return "".join(parts)


def _unwrap_tool_result(tool_name: str, result: Any) -> Dict[str, Any]:
    if getattr(result, "isError", False):
        raise MCPToolError(f"MCP tool '{tool_name}' failed: {_text_of(result.content) or 'no detail'}")

    text = _text_of(result.content)
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP wraps generic return types (Dict[str, Any], list, ...) as
        # {"result": <value>} in structured output while the text content
        # carries <value> itself. Unwrap only when the text confirms it, so a
        # tool whose real output has a lone "result" field keeps it.
        if isinstance(parsed, dict) and set(structured) == {"result"} and structured["result"] == parsed:
            return parsed
        return structured

    if parsed is not None:
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"content": [_dump(b) if hasattr(b, "model_dump") else b for b in (result.content or [])]}
