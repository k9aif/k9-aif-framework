# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Systems of record for read-through and verify — reached through the framework's own adapters."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("k9x.origin.sources")

Fetch = Callable[[str, str], Optional[Dict[str, Any]]]   # (entity, id) -> record or None


def _first_record(result: Any) -> Optional[Dict[str, Any]]:
    """Normalise what a source returned to one record dict (or None when not found)."""
    if result is None:
        return None
    if isinstance(result, dict):   # each source type has already unwrapped its own envelope
        return result or None
    if isinstance(result, list):
        return _first_record(result[0]) if result else None
    return {"value": result}


class OriginSources:
    """
    Named systems of record from ``origin.yaml``:

        sources:
          erp:      { type: mcp,  server: "${ERP_MCP_URL}", tool: get_invoice, args: {invoice_id: "{id}"} }
          treasury: { type: api,  url: "${TREASURY_URL}/payments/{id}", method: GET }     # HttpApiAdapter
          vendors:  { type: sql,  connection: "${AP_DB_URL}",
                      query: "select * from vendors where vendor_id = :id" }             # SqlDataAdapter
          crm:      { type: api,  adapter: my_crm_adapter }       # any registered BaseApiAdapter SBB

    MCP is the main path: data platforms and enterprise systems increasingly ship their own MCP
    servers. Nothing here is a new connector; ``register(name, fetch)`` adds one in code.
    """

    def __init__(self, specs: Optional[Dict[str, Dict[str, Any]]] = None):
        self.specs = dict(specs or {})
        self._fetchers: Dict[str, Fetch] = {}

    def register(self, name: str, fetch: Fetch) -> None:
        self._fetchers[name] = fetch

    def fetch(self, source: str, entity: str, entity_id: str) -> Optional[Dict[str, Any]]:
        fn = self._fetchers.get(source) or self._build(source)
        if fn is None:
            raise KeyError(f"unknown source '{source}' (declare it under sources: in origin.yaml)")
        return _first_record(fn(entity, entity_id))

    # ── built from origin.yaml ─────────────────────────────────────────
    def _build(self, name: str) -> Optional[Fetch]:
        spec = self.specs.get(name)
        if not spec:
            return None
        kind = str(spec.get("type", "mcp")).lower()
        builder = {"mcp": self._mcp, "api": self._api, "sql": self._sql}.get(kind)
        if builder is None:
            raise ValueError(f"source '{name}': unknown type '{kind}' (mcp | api | sql)")
        fn = builder(name, spec)
        self._fetchers[name] = fn
        return fn

    @staticmethod
    def _args(spec: Dict[str, Any], entity: str, entity_id: str) -> Dict[str, Any]:
        template = spec.get("args") or {"id": "{id}"}
        return {k: (str(v).format(id=entity_id, entity=entity) if isinstance(v, str) else v)
                for k, v in template.items()}

    def _mcp(self, name: str, spec: Dict[str, Any]) -> Fetch:
        from k9_aif_abb.k9_core.integration.mcp_streamable_http_connector import MCPStreamableHttpConnector
        from k9_aif_abb.k9_security.tool_result_guard import _run_coro_sync
        conn = MCPStreamableHttpConnector({"name": name, "kwargs": {"url": spec["server"],
                                                                     "timeout": spec.get("timeout", 15)}})

        def fetch(entity: str, entity_id: str):
            return _run_coro_sync(conn.call_tool(spec["tool"], self._args(spec, entity, entity_id)))
        return fetch

    def _api(self, name: str, spec: Dict[str, Any]) -> Fetch:
        from k9_aif_abb.k9_adapters.integration import IntegrationAdapterFactory
        adapter = IntegrationAdapterFactory.get(spec.get("adapter", "http"),
                                                {k: v for k, v in spec.items() if k not in ("type", "adapter")})

        def fetch(entity: str, entity_id: str):
            out = adapter.execute({"id": entity_id, "entity": entity, **self._args(spec, entity, entity_id)})
            if out.get("status") != "success":
                raise RuntimeError(f"source '{name}': {out.get('error')}")
            return out.get("result")
        return fetch

    def _sql(self, name: str, spec: Dict[str, Any]) -> Fetch:
        from k9_aif_abb.k9_adapters.integration import IntegrationAdapterFactory
        adapter = IntegrationAdapterFactory.get(spec.get("adapter", "sql"),
                                                {k: v for k, v in spec.items() if k not in ("type", "adapter")})

        def fetch(entity: str, entity_id: str):
            out = adapter.execute({"query": spec.get("query", ""), "params": {"id": entity_id,
                                                                              **self._args(spec, entity, entity_id)}})
            if out.get("status") != "success":
                raise RuntimeError(f"source '{name}': {out.get('error')}")
            return out.get("rows")
        return fetch
