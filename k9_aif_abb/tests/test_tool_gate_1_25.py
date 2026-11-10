# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
The tool gate (1.25.0): a prompt can't change an agent's code, but it can change the
values the model returns. These tests prove the gate decides on facts the model did
not supply, and that only a valid approval runs a held call, once.

Real components where the property depends on them: real BaseAgent wrapping, real
BaseConnector wrapping, real K9RulesAdapter, real SQLite audit log and RoutingStateStore,
real K9EventRouter reply handling. Fakes only at the edges: the MCP server (a counting
connector), the message bus, k9x Origin's answers.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict

import pytest

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent, _resolve_sync
from k9_aif_abb.k9_core.integration.base_connector import BaseConnector
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_core.tools import (
    BaseToolDispatcher, InMemoryToolCallAuditLog, SQLiteToolCallAuditLog, ToolCall,
    ToolCallDecision, ToolCallDenied, ToolCallPendingReview, ToolRegistry,
)
from k9_aif_abb.k9_core.tools import tool_gate_context
from k9_aif_abb.k9_core.tools.base_tool_dispatcher import reset_shared_audit_logs


# ----------------------------------------------------------------------------- edges
class PassGovernance:
    """Governance that passes everything except a tool named 'blocked_tool'."""

    def pre_process(self, payload, ctx=None):
        if isinstance(payload, dict) and payload.get("tool_name") == "blocked_tool":
            raise PermissionError("k9x_Shield blocked ingress [ToolAuthorizationCheck]")
        return payload

    def post_process(self, payload, ctx=None):
        return payload


class CountingConnector(BaseConnector):
    """Stands in for an MCP server. Its call_tool is wrapped by BaseConnector like any connector."""
    calls: list = []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        CountingConnector.calls.append((tool_name, dict(arguments)))
        return {"ok": True, "tool": tool_name}


class FakeOrigin:
    def __init__(self, records):
        self.records = records

    def get_current(self, entity, entity_id, agent=None):
        value = self.records.get((entity, entity_id))
        if value is None:
            return {"entity": entity, "id": entity_id, "found": False, "flags": {}}
        return {"entity": entity, "id": entity_id, "found": True, "value": value, "flags": {}}


class Bus:
    def __init__(self):
        self.published = []

    def publish_to(self, topic, event):
        self.published.append((topic, event))

    def publish(self, event):
        self.published.append((None, event))


PAYMENT = {"vendor": "V-100", "amount": 4800, "account": "ATTACKER-X"}
RECORDS = {("vendor", "V-100"): {"bank_account": "VENDOR-Y"}}


def gate_cfg(**overrides):
    tools = {
        "release_payment": {
            "irreversible": True,
            "verify": {"account": {"entity": "vendor", "id_from": "vendor", "field": "bank_account"}},
        },
        "lookup_invoice": {"irreversible": False},
    }
    cfg = {"enabled": True, "audit": {"provider": "memory"}, "tools": tools}
    cfg.update(overrides)
    return {"k9_env": "test", "security": {"tool_gate": cfg}}


class PaymentAgent(BaseAgent):
    """Well-built agent code: it calls the tool with the values it was given. It never
    raises RequiresHIL itself; that's the point."""
    layer = "PaymentAgent"

    def __init__(self, config, connector, swallow=False):
        super().__init__(config, governance=PassGovernance())
        self.connector, self.swallow = connector, swallow

    def execute(self, payload):
        args = payload["call"]
        try:
            result = _resolve_sync(self.connector.call_tool(payload.get("tool", "release_payment"), args))
        except RequiresHIL:
            if not self.swallow:
                raise
            return {"output": "carried on as if paid"}
        return {"output": result}


def dispatcher_for(agent, **kw):
    """Give an agent a dispatcher with test collaborators (same object the wrapper would build)."""
    d = BaseToolDispatcher.from_config(agent.config, governance=agent.governance, **kw)
    agent.__dict__["_k9_tool_dispatcher"] = d
    return d


@pytest.fixture(autouse=True)
def _reset():
    CountingConnector.calls = []
    reset_shared_audit_logs()
    before = tool_gate_context._GATE_REQUIRED
    yield
    tool_gate_context._GATE_REQUIRED = before
    reset_shared_audit_logs()


# ----------------------------------------------------------------------------- the misled agent
def test_irreversible_call_is_held_although_the_agent_never_raises_requires_hil():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS))
    with pytest.raises(ToolCallPendingReview) as caught:
        agent.execute({"call": PAYMENT})
    assert CountingConnector.calls == []                       # the payment never ran
    review = caught.value.context
    assert review["kind"] == "tool_call" and review["arguments"] == PAYMENT
    assert review["mismatches"][0]["on_record"] == "VENDOR-Y"  # the person sees the truth
    assert review["call_digest"] == ToolCall("release_payment", PAYMENT).digest()


def test_agent_code_that_swallows_the_review_cannot_hide_it():
    agent = PaymentAgent(gate_cfg(), CountingConnector(), swallow=True)
    dispatcher_for(agent, origin=FakeOrigin(RECORDS))
    with pytest.raises(ToolCallPendingReview):
        agent.execute({"call": PAYMENT})
    assert CountingConnector.calls == []


def test_review_raised_in_a_nested_agent_reaches_the_outer_one():
    inner = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(inner, origin=FakeOrigin(RECORDS))

    class Outer(BaseAgent):
        layer = "Outer"

        def execute(self, payload):
            try:
                inner.execute(payload)
            except RequiresHIL:
                pass                                           # swallowed one level up
            return {"output": "done"}

    with pytest.raises(ToolCallPendingReview):
        Outer(gate_cfg(), governance=PassGovernance()).execute({"call": PAYMENT})
    assert CountingConnector.calls == []


def test_undeclared_tool_is_treated_as_irreversible():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent)
    with pytest.raises(ToolCallPendingReview) as caught:
        agent.execute({"tool": "wire_funds", "call": {"to": "X"}})
    assert "not declared" in caught.value.reason
    assert CountingConnector.calls == []


def test_reversible_tool_runs():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent)
    out = agent.execute({"tool": "lookup_invoice", "call": {"id": "INV-123"}})
    assert out["output"]["ok"] and CountingConnector.calls == [("lookup_invoice", {"id": "INV-123"})]


def test_shield_block_stops_the_call_before_anything_else():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent)
    with pytest.raises(PermissionError):
        agent.execute({"tool": "blocked_tool", "call": {}})
    assert CountingConnector.calls == []


def test_gate_off_leaves_behaviour_unchanged():
    cfg = {"k9_env": "test"}
    agent = PaymentAgent(cfg, CountingConnector())
    agent.execute({"call": PAYMENT})
    assert CountingConnector.calls == [("release_payment", PAYMENT)]


def test_sync_agent_inside_a_running_loop_is_still_gated():
    """The thread bridge copies the caller's context, so the gate follows the call."""
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS))

    async def main():
        return agent.execute({"call": PAYMENT})

    with pytest.raises(ToolCallPendingReview):
        asyncio.run(main())
    assert CountingConnector.calls == []


def test_tool_call_outside_a_gated_agent_is_refused_in_production(monkeypatch):
    tool_gate_context.require_gate()                           # a gate is enabled in this process
    monkeypatch.setenv("K9_ENV", "production")
    with pytest.raises(PermissionError, match="outside a gated agent call"):
        asyncio.run(CountingConnector().call_tool("release_payment", PAYMENT))
    assert CountingConnector.calls == []


# ----------------------------------------------------------------------------- record checks and rules
class Rules:
    def __init__(self, verdict, rule="r1", status="success"):
        self.verdict, self.rule, self.status = verdict, rule, status
        self.seen = None

    def execute(self, payload):
        self.seen = payload
        if self.status != "success":
            return {"status": "error", "error": "engine down"}
        return {"status": "success", "decision": {"decision": self.verdict, "rule": self.rule}}


def test_rules_cannot_allow_a_value_that_does_not_match_its_record():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS), rules_adapter=Rules("allow"))
    with pytest.raises(ToolCallPendingReview, match="don't match the record"):
        agent.execute({"call": PAYMENT})
    assert CountingConnector.calls == []


def test_rules_can_deny_outright():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS), rules_adapter=Rules("deny"))
    with pytest.raises(ToolCallDenied):
        agent.execute({"call": PAYMENT})
    assert CountingConnector.calls == []


def test_matching_record_and_a_named_allow_rule_runs_the_call():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    rules = Rules("allow", rule="known payee under limit")
    dispatcher_for(agent, origin=FakeOrigin(RECORDS), rules_adapter=rules)
    good = {**PAYMENT, "account": "VENDOR-Y"}
    agent.execute({"call": good})
    assert CountingConnector.calls == [("release_payment", good)]
    assert rules.seen["tool_call"]["irreversible"] is True     # the rules saw the framework's facts


def test_matching_record_but_no_rule_still_needs_a_person():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS))
    with pytest.raises(ToolCallPendingReview, match="irreversible"):
        agent.execute({"call": {**PAYMENT, "account": "VENDOR-Y"}})


def test_rules_engine_failure_holds_the_call():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS), rules_adapter=Rules(None, status="error"))
    with pytest.raises(ToolCallPendingReview, match="rules engine unavailable"):
        agent.execute({"call": {**PAYMENT, "account": "VENDOR-Y"}})


def test_no_origin_means_the_value_cannot_be_checked_so_a_person_decides():
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=None, rules_adapter=Rules("allow"))
    with pytest.raises(ToolCallPendingReview, match="no k9x Origin"):
        agent.execute({"call": {**PAYMENT, "account": "VENDOR-Y"}})


def test_real_k9_rules_adapter_no_match_does_not_allow_an_irreversible_call():
    """K9RulesAdapter returns allow when no rule matches; the gate treats that as no decision."""
    from k9_aif_abb.k9_adapters.integration.k9_rules_adapter import K9RulesAdapter
    rules = K9RulesAdapter({"rules": [{"name": "huge", "when": "tool_call.arguments.amount > 100000",
                                       "then": "deny"}]})
    agent = PaymentAgent(gate_cfg(), CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS), rules_adapter=rules)
    with pytest.raises(ToolCallPendingReview):
        agent.execute({"call": {**PAYMENT, "account": "VENDOR-Y"}})
    assert CountingConnector.calls == []


# ----------------------------------------------------------------------------- the reply
def _held(dispatcher, args=PAYMENT):
    call = ToolCall("release_payment", args)
    with pytest.raises(ToolCallPendingReview):
        asyncio.run(dispatcher.propose(call))
    return call


def _dispatcher(clock=None, **kw):
    cfg = gate_cfg()
    return BaseToolDispatcher(cfg, governance=PassGovernance(), audit_log=InMemoryToolCallAuditLog(),
                              origin=FakeOrigin(RECORDS), connector_resolver=lambda spec: CountingConnector(),
                              **({"clock": clock} if clock else {}), **kw)


def test_approval_runs_the_stored_call_exactly_once():
    d = _dispatcher()
    call = _held(d)
    reply = {"correlation_id": call.correlation_id, "action": "complete", "actor": "clerk@acme"}
    assert d.resume(reply)["status"] == "executed"
    assert d.resume(reply)["status"] == "already_decided"      # duplicate delivery
    assert CountingConnector.calls == [("release_payment", PAYMENT)]
    events = [e["event"] for e in d.audit.events(call.correlation_id)]
    assert events[:2] == ["intercepted", "decided"] and "approved" in events and events[-1] == "executed"


@pytest.mark.parametrize("reply_extra,outcome", [
    ({"action": "reject"}, "rejected"),
    ({"action": "expire"}, "expired"),
    ({"action": "approve-ish"}, "malformed"),
    ({"action": "complete", "actor": ""}, "malformed"),
    ({"action": "complete", "result": {"call_digest": "not-this-call"}}, "malformed"),
    ({"action": "complete", "result": {"approved": False}}, "rejected"),
])
def test_anything_but_a_valid_approval_never_runs(reply_extra, outcome):
    d = _dispatcher()
    call = _held(d)
    reply = {"correlation_id": call.correlation_id, "actor": "clerk@acme", **reply_extra}
    out = d.resume(reply)
    assert out["status"] == "not_executed" and out["outcome"] == outcome
    assert d.resume({**reply, "action": "complete", "actor": "clerk@acme"})["status"] == "already_decided"
    assert CountingConnector.calls == []


def test_a_late_approval_does_not_run():
    now = [1000.0]
    d = _dispatcher(clock=lambda: now[0])
    call = _held(d)
    now[0] += 86400 + 1
    out = d.resume({"correlation_id": call.correlation_id, "action": "complete", "actor": "clerk@acme"})
    assert out["outcome"] == "expired" and CountingConnector.calls == []


def test_expiry_rejects_by_default_and_approve_is_possible_with_a_warning(caplog):
    now = [1000.0]
    d = _dispatcher(clock=lambda: now[0])
    _held(d)
    now[0] += 86401
    assert d.expire_stale()[0]["outcome"] == "expired" and CountingConnector.calls == []

    cfg = gate_cfg(on_expiry="approve")
    with caplog.at_level("WARNING"):
        d2 = BaseToolDispatcher(cfg, governance=PassGovernance(), audit_log=InMemoryToolCallAuditLog(),
                                origin=FakeOrigin(RECORDS), connector_resolver=lambda s: CountingConnector(),
                                clock=lambda: now[0])
    assert "will RUN" in caplog.text
    _held(d2)
    now[0] += 86401
    assert d2.expire_stale()[0]["status"] == "executed"


def test_digest_echo_can_be_required():
    d = _dispatcher()
    d.require_digest_echo = True
    call = _held(d)
    base = {"correlation_id": call.correlation_id, "action": "complete", "actor": "clerk@acme"}
    assert d.resume(base)["outcome"] == "malformed"
    call2 = _held(d)
    ok = {**base, "correlation_id": call2.correlation_id, "result": {"call_digest": call2.digest()}}
    assert d.resume(ok)["status"] == "executed"


def test_decision_parser_rejects_a_reply_for_another_call():
    pending = {"correlation_id": "a", "digest": "d", "expires_at": None}
    assert ToolCallDecision.parse({"correlation_id": "b", "action": "complete", "actor": "x"},
                                  pending).outcome == "malformed"


# ----------------------------------------------------------------------------- audit log
def test_sqlite_audit_events_are_append_only(tmp_path):
    log = SQLiteToolCallAuditLog(str(tmp_path / "t.db"))
    log.record("c1", "intercepted", {"tool": "x"})
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE tool_call_events SET event = 'executed'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM tool_call_events")


def test_sqlite_transition_is_compare_and_swap(tmp_path):
    log = SQLiteToolCallAuditLog(str(tmp_path / "t.db"))
    log.create_pending("c1", {"expires_at": 5.0})
    assert log.transition("c1", ["pending"], "executing") is True
    assert log.transition("c1", ["pending"], "executing") is False
    assert log.get_pending("c1")["status"] == "executing"


def test_registry_is_frozen():
    reg = ToolRegistry.from_config({"t": {"irreversible": False}})
    with pytest.raises(TypeError):
        reg._specs["t"] = None
    with pytest.raises(ValueError):
        ToolRegistry.from_config({"t": {"irreversible": "no"}})


# ----------------------------------------------------------------------------- end to end
def test_round_trip_router_orchestrator_agent_and_back(tmp_path):
    """Agent holds the call -> Orchestrator publishes the review under the call's id ->
    the reviewer's reply comes back through the Router -> the stored call runs once."""
    from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter
    from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
    from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage

    store = RoutingStateStore(db=SQLiteDatabaseStorage(db_path=":memory:"))
    bus = Bus()
    config = {**gate_cfg(audit={"db_path": str(tmp_path / "tool_calls.db")}),
              "routing": {"table": {"invoice": "payments.in"}, "hil": {"prefix": "hil."}}}
    config["security"]["tool_gate"]["tools"]["release_payment"]["connector"] = {"client": "counting"}
    from k9_aif_abb.k9_factories.mcp_client_connection_factory import MCPClientConnectionFactory
    MCPClientConnectionFactory.register("counting", CountingConnector)

    agent = PaymentAgent(config, CountingConnector())
    dispatcher_for(agent, origin=FakeOrigin(RECORDS))

    class PaymentsOrchestrator(BaseOrchestrator):
        layer = "Payments"

        def execute_flow(self, payload):
            resumed = self.resume_tool_call(payload)
            if resumed is not None:
                return resumed
            try:
                return {"status": "completed", **agent.execute(payload)}
            except RequiresHIL as exc:
                return self.handle_requires_hil(exc, payload)

    orch = PaymentsOrchestrator(config=config, message_bus=bus, hil_state_store=store,
                                governance=PassGovernance())
    orch._tool_dispatcher = BaseToolDispatcher.from_config(config, governance=PassGovernance(),
                                                           origin=FakeOrigin(RECORDS))
    router = K9EventRouter(config=config, message_bus=bus, state_store=store)

    event = {"event_type": "invoice", "call": PAYMENT}
    held = orch.execute_flow(event)
    assert held["status"] == "pending_hil" and CountingConnector.calls == []
    cid = held["correlation_id"]
    request = [e for t, e in bus.published if t == "hil.requests.tool-review"][0]
    assert request["correlation_id"] == cid                     # published under the held call's id
    assert request["payload"]["mismatches"][0]["on_record"] == "VENDOR-Y"

    asyncio.run(router._on_hil_reply({"correlation_id": cid, "action": "complete", "actor": "clerk@acme"}))
    resumed = [e for t, e in bus.published if t == "payments.in"][-1]
    assert orch.execute_flow(resumed)["status"] == "executed"
    assert orch.execute_flow(resumed)["status"] == "already_decided"
    assert CountingConnector.calls == [("release_payment", PAYMENT)]
