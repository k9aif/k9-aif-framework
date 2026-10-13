# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""ContextMCPServer — serve live context (BaseContextState) to agents over MCP."""

from __future__ import annotations

import inspect
import time
import json
from typing import Any, Callable, Dict, Iterable, Optional

from k9_aif_abb.k9_core.streams.base_context_state import BaseContextState
from k9_aif_abb.k9_mcp.servers.base_mcp_server import BaseMCPServer

CallListener = Callable[[Dict[str, Any]], None]


class ContextMCPServer(BaseMCPServer):
    """
    The MCP surface of the context fabric: agents ask for current enterprise state
    here instead of reading Kafka. Three tools, every answer stamped with ``as_of``,
    ``age_seconds``, ``stale`` and the source event:

      get_current(entity, id)                    latest value of one entity
      recent_changes(entity, id, window_seconds) what changed lately, oldest first
      query(entity, status, min_amount)          entities of one type, filtered

    plus the resource ``context://{entity}/{id}`` (same as get_current).

    Agents call it with the framework's own client — ``MCPStreamableHttpConnector``
    (``MCPClientConnectionFactory.get("streamable_http", ...)``) — and screen each
    result with ``screen_tool_result`` like any other tool result.

    Three optional controls, each a line of defence of its own:

    ``allowed_entities``   scope: the entity types this server will answer about
                           (``{"invoice", "vendor"}``); anything else is refused
                           before the state is read.
    ``request_governance`` screens what an agent *asks* before any data is read —
                           injection hidden in arguments, solicitations for PII
                           (``PromptInjectionCheck``, ``PIIRequestCheck``).
    ``governance``         screens every answer before it leaves the server — PII
                           values (``PIIBoundaryCheck`` with ``block_on_match``),
                           planted instructions; a refused answer is replaced by the
                           framework's withheld notice.

    Events refused at ingress never reach the state at all (``GovernanceEventGate``).
    A refused request returns ``{"refused_by_governance": True, "reason": ...}``.

    ``handle_request()`` serves the K9-AIF request shape without a network;
    ``build_fastmcp()`` returns a FastMCP server (``pip install "k9-aif[mcp]"``)
    whose ``streamable_http_app()`` can be mounted in any ASGI app::

        server = ContextMCPServer(state, name="k9x-streams")
        mcp = server.build_fastmcp()
        app.mount("/", mcp.streamable_http_app())   # MCP at /mcp
        # FastAPI lifespan:  async with mcp.session_manager.run(): yield
    """

    layer = "MCP SBB"
    TOOLS = ("get_current", "recent_changes", "query")

    def __init__(self, state: BaseContextState, name: str = "k9-context",
                 instructions: Optional[str] = None, governance: Any = None,
                 on_call: Optional[CallListener] = None, monitor: Optional[Any] = None,
                 request_governance: Any = None, allowed_entities: Optional[Iterable[str]] = None):
        super().__init__(name=name, monitor=monitor)
        self.state = state
        self.governance = governance
        self.request_governance = request_governance
        self.allowed_entities = {e.lower() for e in allowed_entities} if allowed_entities else None
        self.on_call = on_call
        self.instructions = instructions or (
            "Live enterprise state built from event streams. Every result has as_of, "
            "age_seconds and stale; do not act on stale values.")

    # ── tools ───────────────────────────────────────────────────────────
    def get_current(self, entity: str, id: str) -> Dict[str, Any]:
        return self._serve("get_current", {"entity": entity, "id": id},
                           lambda: self.state.get_current(entity, id))

    def recent_changes(self, entity: str, id: str, window_seconds: float = 600) -> Dict[str, Any]:
        return self._serve("recent_changes", {"entity": entity, "id": id, "window_seconds": window_seconds},
                           lambda: self.state.recent_changes(entity, id, window_seconds))

    def query(self, entity: str, status: str = "", min_amount: float = 0) -> Dict[str, Any]:
        return self._serve("query", {"entity": entity, "status": status, "min_amount": min_amount},
                           lambda: self.state.query(entity, filters={"status": status},
                                                    minimum={"amount": min_amount}))

    def _refusal(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Why this request may not be answered (scope, then request screening), or None."""
        entity = str(args.get("entity", "")).lower()
        if self.allowed_entities is not None and entity not in self.allowed_entities:
            return f"entity '{entity}' is outside this server's scope ({', '.join(sorted(self.allowed_entities))})"
        if self.request_governance is not None:
            payload = {"query": json.dumps(args, default=str), "source": "mcp_request", "source_tool": tool}
            try:
                from k9_aif_abb.k9_security.tool_result_guard import _run_coro_sync
                outcome = self.request_governance.pre_process(payload, {"component": f"mcp:{self.name}:{tool}"})
                if inspect.isawaitable(outcome):
                    _run_coro_sync(outcome)
            except PermissionError as exc:
                return str(exc)
        return None

    def _serve(self, tool: str, args: Dict[str, Any], read: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        t0 = time.time()
        reason = self._refusal(tool, args)
        if reason is not None:
            self.logger.warning("[ContextMCP] refused %s %s: %s", tool, args, reason)
            out = {"refused_by_governance": True, "reason": reason, "tool": tool}
            self._notify(tool, args, t0, out, "refused")
            return out
        out = read()
        screened = "passed"
        if self.governance is not None:
            from k9_aif_abb.k9_security.tool_result_guard import (
                _run_coro_sync, screen_tool_result, withheld_value)
            try:
                _run_coro_sync(screen_tool_result(self.governance, tool, out, {"component": self.name}))
            except PermissionError as exc:
                out, screened = withheld_value(out, str(exc)), "withheld"
        self._notify(tool, args, t0, out, screened)
        return out

    def _notify(self, tool: str, args: Dict[str, Any], t0: float, out: Dict[str, Any], screened: str) -> None:
        if self.on_call:
            try:
                self.on_call({"tool": tool, "args": args, "ms": round((time.time() - t0) * 1000, 1),
                              "as_of": out.get("as_of"), "age_seconds": out.get("age_seconds"),
                              "found": out.get("found", True), "screened": screened,
                              "reason": out.get("reason")})
            except Exception:
                self.logger.exception("on_call listener failed")

    # ── BaseMCPServer contract ──────────────────────────────────────────
    async def handle_request(self, request: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``{"tool": "get_current", "arguments": {"entity": "invoice", "id": "INV-1"}}`` → result dict."""
        tool = request.get("tool") or request.get("name")
        if tool not in self.TOOLS:
            return {"error": f"unknown tool {tool!r}; one of {list(self.TOOLS)}"}
        result = getattr(self, tool)(**(request.get("arguments") or {}))
        return await result if inspect.isawaitable(result) else result

    # ── network transport ───────────────────────────────────────────────
    def build_fastmcp(self, **kwargs: Any) -> Any:
        """A FastMCP server exposing the three tools and the context:// resource.
        kwargs go to FastMCP (default stateless_http=True: one request, one answer)."""
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError as exc:   # pragma: no cover - depends on the extra
            raise RuntimeError('pip install "k9-aif[mcp]" required for ContextMCPServer.build_fastmcp') from exc

        kwargs.setdefault("stateless_http", True)
        mcp = FastMCP(self.name, instructions=self.instructions, **kwargs)
        server = self

        @mcp.tool()
        def get_current(entity: str, id: str) -> Dict[str, Any]:
            """Latest state of one entity, with as_of, age_seconds, stale and its source event."""
            return server.get_current(entity, id)

        @mcp.tool()
        def recent_changes(entity: str, id: str, window_seconds: float = 600) -> Dict[str, Any]:
            """What changed for one entity within the last window_seconds, oldest first."""
            return server.recent_changes(entity, id, window_seconds)

        @mcp.tool()
        def query(entity: str, status: str = "", min_amount: float = 0) -> Dict[str, Any]:
            """Entities of one type, optionally by status and minimum amount."""
            return server.query(entity, status, min_amount)

        @mcp.resource("context://{entity}/{id}")
        def entity_resource(entity: str, id: str) -> Dict[str, Any]:
            """The same live state as get_current, as an MCP resource."""
            return server.state.get_current(entity, id)

        return mcp
