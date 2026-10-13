# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""OriginMCPServer — k9x Origin's three operations over MCP."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from k9_aif_abb.k9_mcp.servers.context_mcp_server import ContextMCPServer


class OriginMCPServer(ContextMCPServer):
    """
    k9x Origin over MCP: ``get_current``, ``recent_changes``, ``query`` (filters as a dict) and the
    ``origin://{entity}/{id}`` resource. Scope, request screening, read-through, verify, flags and
    answer screening all happen in Origin; this class only carries the calls.

    ``agent`` scopes the server to one agent's ``allowed_entities`` and ``verify_before`` steps in
    origin.yaml (mount one per agent when agents need different scopes); ``None`` serves the
    solution's whole scope.

        server = OriginMCPServer(origin, name="ap-origin")
        app.mount("/", server.http_app())                 # MCP at /mcp
        server.register_on(existing_mcp)                  # or: add the tools to an existing MCP server
    """

    def __init__(self, origin: Any, name: str = "k9x-origin", agent: Optional[str] = None,
                 instructions: Optional[str] = None, on_call=None, monitor=None):
        super().__init__(origin.state, name=name, monitor=monitor, on_call=on_call,
                         instructions=instructions or (
                             "k9x Origin: what is true right now about an entity, and where it came from. "
                             "Every answer has as_of, source, version and flags; quarantined, in_review or "
                             "conflict flags mean the data must not be acted on without review."))
        self.origin = origin
        self.agent = agent

    def get_current(self, entity: str, id: str) -> Dict[str, Any]:
        return self._carry("get_current", {"entity": entity, "id": id},
                           lambda: self.origin.get_current(entity, id, agent=self.agent))

    def recent_changes(self, entity: str, id: str, window_seconds: float = 600) -> Dict[str, Any]:
        return self._carry("recent_changes", {"entity": entity, "id": id, "window_seconds": window_seconds},
                           lambda: self.origin.recent_changes(entity, id, window_seconds, agent=self.agent))

    def query(self, entity: str, filters: Optional[Dict[str, Any]] = None,
              minimum: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        return self._carry("query", {"entity": entity, "filters": filters or {}, "minimum": minimum or {}},
                           lambda: self.origin.query(entity, filters=filters, minimum=minimum, agent=self.agent))

    def _carry(self, tool: str, args: Dict[str, Any], call) -> Dict[str, Any]:
        t0 = time.time()
        out = call()
        screened = ("refused" if out.get("refused_by_governance") else
                    "withheld" if out.get("withheld_by_governance") else "passed")
        self._notify(tool, args, t0, out, screened)
        return out

    def register_on(self, mcp: Any) -> Any:
        server = self

        @mcp.tool()
        def get_current(entity: str, id: str) -> Dict[str, Any]:
            """What is true right now about one entity: value, as_of, source, version and flags."""
            return server.get_current(entity, id)

        @mcp.tool()
        def recent_changes(entity: str, id: str, window_seconds: float = 600) -> Dict[str, Any]:
            """What changed for one entity within the last window_seconds, in source order."""
            return server.recent_changes(entity, id, window_seconds)

        @mcp.tool()
        def query(entity: str, filters: Optional[Dict[str, Any]] = None,
                  minimum: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
            """Entities of one type whose fields equal `filters` and are at least `minimum`."""
            return server.query(entity, filters, minimum)

        @mcp.resource("origin://{entity}/{id}")
        def origin_resource(entity: str, id: str) -> Dict[str, Any]:
            """The same answer as get_current, as an MCP resource."""
            return server.get_current(entity, id)

        return mcp
