# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# MCPStreamableHttpConnector -- the standard MCP streamable-HTTP client.
#
# Three layers:
#   1. result unwrapping + config, against a fake session (no network)
#   2. the real MCP protocol, against a FastMCP server started in-process
#      on a free localhost port (needs the `mcp` + `uvicorn` packages)
#   3. an optional live check against a deployed server, run only when
#      MCP_SERVER_URL is set, e.g.
#        MCP_SERVER_URL=http://mcp-host:8765/mcp pytest k9_aif_abb/tests/test_mcp_streamable_http_connector.py -v

import asyncio
import importlib.util
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from k9_aif_abb.k9_core.integration.mcp_streamable_http_connector import (
    MCPStreamableHttpConnector,
    MCPToolError,
)
from k9_aif_abb.k9_factories.mcp_client_connection_factory import MCPClientConnectionFactory


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Config + result unwrapping (fake session)
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, result=None, tools=None):
        self.result = result
        self.tools = tools
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result

    async def list_tools(self):
        return self.tools


def _connector_with(session, **kwargs):
    conn = MCPStreamableHttpConnector({"name": "t", "kwargs": {"url": "http://x/mcp", **kwargs}})

    @asynccontextmanager
    async def fake_session():
        yield session

    conn._session = fake_session
    return conn


def _text(text):
    return SimpleNamespace(text=text, type="text")


def test_requires_url():
    with pytest.raises(ValueError, match="url"):
        MCPStreamableHttpConnector({"kwargs": {}})


def test_accepts_base_url_and_top_level_keys():
    assert MCPStreamableHttpConnector({"kwargs": {"base_url": "http://a/mcp"}}).url == "http://a/mcp"
    assert MCPStreamableHttpConnector({"url": "http://b/mcp"}).url == "http://b/mcp"


def test_api_key_becomes_bearer_header_alongside_extra_headers():
    conn = MCPStreamableHttpConnector({"kwargs": {"url": "http://x/mcp", "api_key": "k", "headers": {"X-T": "1"}}})
    assert conn._request_headers() == {"X-T": "1", "Authorization": "Bearer k"}


def test_structured_content_is_preferred():
    result = SimpleNamespace(isError=False, structuredContent={"risk_level": "low"}, content=[_text('{"other": 1}')])
    session = _FakeSession(result=result)
    out = _run(_connector_with(session).call_tool("screen", {"vendor_name": "V"}))
    assert out == {"risk_level": "low"}
    assert session.calls == [("screen", {"vendor_name": "V"})]


def test_sdk2_snake_case_fields_are_read():
    ok = SimpleNamespace(is_error=False, structured_content={"risk_level": "low"}, content=[])
    assert _run(_connector_with(_FakeSession(result=ok)).call_tool("t", {})) == {"risk_level": "low"}
    failed = SimpleNamespace(is_error=True, structured_content=None, content=[_text("denied")])
    with pytest.raises(MCPToolError, match="denied"):
        _run(_connector_with(_FakeSession(result=failed)).call_tool("t", {}))


def test_fastmcp_result_wrapper_is_unwrapped_when_text_confirms_it():
    value = {"match_score": 0.0, "risk_level": "NONE"}
    result = SimpleNamespace(isError=False, structuredContent={"result": value},
                             content=[_text('{"match_score": 0.0, "risk_level": "NONE"}')])
    assert _run(_connector_with(_FakeSession(result=result)).call_tool("screen", {})) == value


def test_genuine_result_field_is_kept():
    """A tool whose real output is {"result": ...} is not unwrapped: its text says so."""
    result = SimpleNamespace(isError=False, structuredContent={"result": {"ok": True}},
                             content=[_text('{"result": {"ok": true}}')])
    assert _run(_connector_with(_FakeSession(result=result)).call_tool("t", {})) == {"result": {"ok": True}}


def test_json_text_content_is_parsed_when_no_structured_content():
    result = SimpleNamespace(isError=False, structuredContent=None, content=[_text('{"match_result": "matched"}')])
    assert _run(_connector_with(_FakeSession(result=result)).call_tool("match", {})) == {"match_result": "matched"}


def test_non_dict_json_is_wrapped():
    result = SimpleNamespace(isError=False, structuredContent=None, content=[_text("[1, 2]")])
    assert _run(_connector_with(_FakeSession(result=result)).call_tool("t", {})) == {"result": [1, 2]}


def test_plain_text_is_returned_as_content_blocks():
    result = SimpleNamespace(isError=False, structuredContent=None, content=[{"type": "text", "text": "hello"}])
    assert _run(_connector_with(_FakeSession(result=result)).call_tool("t", {})) == {
        "content": [{"type": "text", "text": "hello"}]
    }


def test_tool_error_raises():
    result = SimpleNamespace(isError=True, structuredContent=None, content=[_text("invoice not found")])
    with pytest.raises(MCPToolError, match="invoice not found"):
        _run(_connector_with(_FakeSession(result=result)).call_tool("retrieve_invoice_data", {}))


def test_factory_registers_builtin_transports():
    conn = MCPClientConnectionFactory.get("streamable_http", config={"kwargs": {"url": "http://x/mcp"}})
    assert isinstance(conn, MCPStreamableHttpConnector)
    if importlib.util.find_spec("httpx"):
        from k9_aif_abb.k9_core.integration.mcp_http_connector import MCPHttpConnector
        assert isinstance(MCPClientConnectionFactory.get("http", config={"kwargs": {}}), MCPHttpConnector)
    with pytest.raises(ValueError, match="Unknown MCP client"):
        MCPClientConnectionFactory.get("carrier_pigeon", config={})


def test_factory_bootstrap_keeps_solution_registrations():
    class Custom(MCPStreamableHttpConnector):
        pass

    saved = dict(MCPClientConnectionFactory._registry), MCPClientConnectionFactory._bootstrapped
    try:
        MCPClientConnectionFactory._registry.clear()
        MCPClientConnectionFactory._bootstrapped = False
        MCPClientConnectionFactory.register("streamable_http", Custom)
        MCPClientConnectionFactory.bootstrap()
        assert MCPClientConnectionFactory._registry["streamable_http"] is Custom
        assert "stdio" in MCPClientConnectionFactory._registry
    finally:
        MCPClientConnectionFactory._registry.clear()
        MCPClientConnectionFactory._registry.update(saved[0])
        MCPClientConnectionFactory._bootstrapped = saved[1]


# ---------------------------------------------------------------------------
# 2. Real protocol against an in-process FastMCP server
# ---------------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def local_mcp_server():
    pytest.importorskip("mcp")
    uvicorn = pytest.importorskip("uvicorn")
    try:
        from mcp.server.mcpserver import MCPServer as ServerClass   # SDK 2.x
    except ImportError:
        from mcp.server.fastmcp import FastMCP as ServerClass       # SDK 1.x

    mcp_server = ServerClass("k9-test-tools")

    @mcp_server.tool()
    def screen_vendor(vendor_name: str, country: str) -> dict:
        """Screen a vendor against a sanctions list."""
        hit = vendor_name.lower().startswith("blocked")
        return {"vendor_name": vendor_name, "country": country, "risk_level": "high" if hit else "low"}

    @mcp_server.tool()
    def lookup_invoice(invoice_id: str) -> Dict[str, Any]:
        """Generic return type: FastMCP wraps the structured output as {"result": ...}."""
        return {"invoice_id": invoice_id, "amount": 4500.0}

    @mcp_server.tool()
    def fail_always(reason: str) -> dict:
        """Always fails."""
        raise ValueError(reason)

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        mcp_server.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            pytest.fail("in-process MCP server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def test_protocol_list_tools(local_mcp_server):
    conn = MCPStreamableHttpConnector({"kwargs": {"url": local_mcp_server}})
    tools = _run(conn.list_tools())["tools"]
    names = {t["name"] for t in tools}
    assert {"screen_vendor", "fail_always"} <= names
    schema = next(t for t in tools if t["name"] == "screen_vendor")["inputSchema"]
    assert schema["type"] == "object" and "vendor_name" in schema["properties"]


def test_protocol_call_tool_returns_structured_result(local_mcp_server):
    conn = MCPStreamableHttpConnector({"kwargs": {"url": local_mcp_server}})
    out = _run(conn.call_tool("screen_vendor", {"vendor_name": "Blocked Corp", "country": "US"}))
    assert out == {"vendor_name": "Blocked Corp", "country": "US", "risk_level": "high"}


def test_protocol_generic_return_type_is_unwrapped(local_mcp_server):
    conn = MCPStreamableHttpConnector({"kwargs": {"url": local_mcp_server}})
    assert _run(conn.call_tool("lookup_invoice", {"invoice_id": "INV-1"})) == {"invoice_id": "INV-1", "amount": 4500.0}


def test_protocol_tool_failure_raises(local_mcp_server):
    conn = MCPStreamableHttpConnector({"kwargs": {"url": local_mcp_server}})
    # SDK 1.x servers return the exception text; 2.x servers hide it by design
    with pytest.raises(MCPToolError, match="fail_always"):
        _run(conn.call_tool("fail_always", {"reason": "boom"}))


def test_protocol_repeated_calls_across_event_loops(local_mcp_server):
    """Session-per-call: each asyncio.run() is a new loop and task, and every call still works."""
    conn = MCPStreamableHttpConnector({"kwargs": {"url": local_mcp_server}})
    for name in ("A", "B", "C"):
        assert _run(conn.call_tool("screen_vendor", {"vendor_name": name, "country": "US"}))["risk_level"] == "low"


def test_rest_connector_cannot_reach_standard_server(local_mcp_server):
    """Documents why this connector exists: MCPHttpConnector's REST paths 404 on a standard MCP server."""
    httpx = pytest.importorskip("httpx")
    from k9_aif_abb.k9_core.integration.mcp_http_connector import MCPHttpConnector
    conn = MCPHttpConnector({"kwargs": {"base_url": local_mcp_server}})
    with pytest.raises(httpx.HTTPStatusError):
        _run(conn.call_tool("screen_vendor", {"vendor_name": "A", "country": "US"}))


# ---------------------------------------------------------------------------
# 3. Optional live check against a deployed server
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("MCP_SERVER_URL"), reason="set MCP_SERVER_URL to run against a deployed MCP server")
def test_live_deployed_server_lists_and_calls_tools():
    conn = MCPStreamableHttpConnector({"kwargs": {"url": os.environ["MCP_SERVER_URL"]}})
    tools = _run(conn.list_tools())["tools"]
    assert tools, "deployed MCP server exposes no tools"
    names = {t["name"] for t in tools}
    if "screen_sanctions_list" in names:
        out = _run(conn.call_tool(
            "screen_sanctions_list", {"vendor_name": "K9X Integration Test Vendor", "country": "US", "aliases": []},
        ))
        assert "risk_level" in out
