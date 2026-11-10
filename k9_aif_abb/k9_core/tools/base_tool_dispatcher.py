# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseToolDispatcher: the one place a tool call is decided and run (1.25.0, opt-in).

With ``security.tool_gate.enabled: true``, every ``BaseConnector.call_tool()`` made
inside a governed agent call is intercepted and proposed here; the agent's code
is unchanged. A prompt can't change an agent's code, but it can change the values
the model returns, so the dispatcher decides on facts the model did not supply:

1. Shield screens the tool name and arguments (``screen_tool_call``); a BLOCK
   raises ``PermissionError``.
2. The ``ToolRegistry`` says whether the tool is irreversible (undeclared: yes)
   and which arguments must match which record.
3. Each record check is looked up through k9x Origin by the dispatcher itself.
   Whether the agent asked Origin makes no difference.
4. The solution's own rules (any ``BaseRulesAdapter``) see those facts and answer
   ``allow``, ``deny`` or ``hil``. The rules can make a call stricter, never looser:
   a value that doesn't match its record, or can't be checked, never runs without
   a person; an irreversible call runs without a person only when a named rule
   explicitly allows it.
5. ``allow`` runs the call. ``deny`` raises ``ToolCallDenied``. ``hil`` stores the
   exact call and raises ``ToolCallPendingReview`` (a ``RequiresHIL``): the
   Orchestrator publishes the review, as for any ``RequiresHIL``. If the agent's
   code catches it, the governed ``BaseAgent`` wrapper raises it again.
6. On the reviewer's reply, ``resume()`` runs the stored call (never a
   re-proposal) at most once, and only on a valid approval.

Every step is recorded in a ``BaseToolCallAuditLog``.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_core.tools.tool_call import ToolCall
from k9_aif_abb.k9_core.tools.tool_call_audit_log import (
    BaseToolCallAuditLog,
    InMemoryToolCallAuditLog,
    SQLiteToolCallAuditLog,
)
from k9_aif_abb.k9_core.tools.tool_call_decision import DEFAULT_APPROVE_ACTIONS, ToolCallDecision
from k9_aif_abb.k9_core.tools.tool_gate_context import GateSession, framework_tool_call
from k9_aif_abb.k9_core.tools.tool_registry import ToolRegistry, ToolSpec

log = logging.getLogger("k9.tool_gate")

VERDICTS = ("allow", "deny", "hil")


class ToolCallPendingReview(RequiresHIL):
    """A tool call is waiting for a person. Raised by the dispatcher; the call has not run."""

    def __init__(self, reason: str, context: Dict[str, Any], correlation_id: str,
                 queue: Optional[str] = None, priority: str = "high"):
        super().__init__(reason, context=context, priority=priority, queue=queue,
                         correlation_id=correlation_id)


class ToolCallDenied(PermissionError):
    """The solution's rules refused the tool call. It has not run."""


def gate_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return ((config or {}).get("security") or {}).get("tool_gate") or {}


def gate_enabled(config: Optional[Dict[str, Any]]) -> bool:
    return bool(gate_config(config).get("enabled"))


class BaseToolDispatcher:
    """See the module docstring. Build with ``from_config()``; pass collaborators to override."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, *, governance: Any = None,
                 registry: Optional[ToolRegistry] = None, rules_adapter: Any = None,
                 origin: Any = None, audit_log: Optional[BaseToolCallAuditLog] = None,
                 connector_resolver: Optional[Callable[[ToolSpec], Any]] = None,
                 clock: Callable[[], float] = time.time):
        self.config = config or {}
        cfg = gate_config(self.config)
        self.governance = governance
        self.registry = registry if registry is not None else ToolRegistry.from_config(cfg.get("tools"))
        self.rules_adapter = rules_adapter
        self.origin = origin
        self.audit = audit_log if audit_log is not None else _audit_from_config(cfg)
        self.connector_resolver = connector_resolver
        self.clock = clock
        self.queue = cfg.get("queue", "tool-review")
        self.deadline_seconds = float(cfg.get("deadline_seconds", 86400))
        self.approve_actions = tuple(cfg.get("approve_actions") or DEFAULT_APPROVE_ACTIONS)
        self.require_digest_echo = bool(cfg.get("require_digest_echo", False))
        self.on_expiry = cfg.get("on_expiry", "reject")
        if self.on_expiry not in ("reject", "approve"):
            raise ValueError("security.tool_gate.on_expiry must be 'reject' or 'approve'")
        if self.on_expiry == "approve":
            log.warning("[ToolGate] on_expiry is 'approve': a pending tool call whose review expires will RUN "
                        "without anyone approving it. 'reject' (the default) is the safe setting.")

    @classmethod
    def from_config(cls, config: Dict[str, Any], *, governance: Any = None, **overrides) -> "BaseToolDispatcher":
        cfg = gate_config(config)
        if "rules_adapter" not in overrides and cfg.get("rules"):
            from k9_aif_abb.k9_adapters.integration import IntegrationAdapterFactory
            rules = dict(cfg["rules"])
            overrides["rules_adapter"] = IntegrationAdapterFactory.get(
                rules.pop("adapter", "k9_rules"), rules)
        if "origin" not in overrides:
            registry = overrides.get("registry") or ToolRegistry.from_config(cfg.get("tools"))
            overrides.setdefault("registry", registry)
            if any(registry.lookup(n).verify for n in registry.names()):
                from k9_aif_abb.k9_factories.origin_factory import OriginFactory
                overrides["origin"] = OriginFactory.create(config)
        return cls(config, governance=governance, **overrides)

    # ------------------------------------------------------------------ propose
    async def propose(self, call: ToolCall, connector: Any = None,
                      session: Optional[GateSession] = None) -> Any:
        """Decide one intercepted call; run it, refuse it, or hold it for a person."""
        cid = call.correlation_id
        self.audit.record(cid, "intercepted", call.to_dict())
        await self._screen(call)

        spec = self.registry.lookup(call.tool_name)
        checks = self._check_records(spec, call.arguments)
        facts = {
            "tool": call.tool_name,
            "arguments": call.arguments,
            "declared": spec.declared,
            "irreversible": spec.irreversible,
            "untrusted_input": session.untrusted_input if session else True,
            "mismatches": checks["mismatches"],
            "verification_unavailable": checks["unavailable"],
            "agent": call.agent_id,
            "request_id": call.request_id,
        }
        verdict, rule, reason = self._decide(spec, facts)
        self.audit.record(cid, "decided", {"verdict": verdict, "rule": rule, "reason": reason, "facts": facts})

        if verdict == "allow":
            return await self._run(call, connector, spec, decided_by=rule or "framework")
        if verdict == "deny":
            self.audit.record(cid, "denied", {"rule": rule, "reason": reason})
            raise ToolCallDenied(f"[ToolGate] {call.tool_name} refused: {reason}")

        now = self.clock()
        record = {
            "call": call.to_dict(),
            "digest": call.digest(),
            "facts": facts,
            "reason": reason,
            "rule": rule,
            "tool_spec": {"name": spec.name, "connector": dict(spec.connector)},
            "created_at": now,
            "expires_at": now + self.deadline_seconds,
        }
        self.audit.create_pending(cid, record)
        if connector is not None:
            self._held_connectors[cid] = connector
        review = self._review(call, facts, reason, record["expires_at"])
        exc = ToolCallPendingReview(reason, context=review, correlation_id=cid,
                                    queue=spec.queue or self.queue)
        if session is not None:
            session.hold(exc)
        self.audit.record(cid, "held_for_review", {"queue": spec.queue or self.queue, "reason": reason})
        raise exc

    @property
    def _held_connectors(self) -> Dict[str, Any]:
        # same-process resume can use the connector the call was made on
        if not hasattr(self, "_held"):
            self._held: Dict[str, Any] = {}
        return self._held

    async def _screen(self, call: ToolCall) -> None:
        from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance
        from k9_aif_abb.k9_security.tool_result_guard import screen_tool_call
        governance = self.governance if self.governance is not None else NoopGovernance()
        try:  # NoopGovernance is refused outside development/test by screen_tool_call itself
            await screen_tool_call(governance, call.tool_name, call.arguments,
                                   {"agent": call.agent_id, "request_id": call.request_id})
        except PermissionError as exc:
            self.audit.record(call.correlation_id, "denied", {"by": "shield", "reason": str(exc)[:500]})
            raise

    def _check_records(self, spec: ToolSpec, arguments: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        mismatches: List[Dict[str, Any]] = []
        unavailable: List[Dict[str, Any]] = []
        for check in spec.verify:
            where = {"argument": check.argument, "entity": check.entity, "field": check.field}
            if check.argument not in arguments or check.id_from not in arguments:
                mismatches.append({**where, "problem": "argument missing from the call"})
                continue
            if self.origin is None:
                unavailable.append({**where, "problem": "no k9x Origin configured to look the record up"})
                continue
            try:
                with framework_tool_call():
                    answer = self.origin.get_current(check.entity, str(arguments[check.id_from]))
            except Exception as exc:  # the lookup failed: the value can't be checked, so a person decides
                log.warning("[ToolGate] record check %s.%s failed: %s", check.entity, check.field, exc)
                unavailable.append({**where, "problem": f"lookup failed: {exc}"})
                continue
            problem = _record_problem(answer, check.field, arguments[check.argument])
            if problem == "unavailable":
                unavailable.append({**where, "problem": _why_unavailable(answer)})
            elif problem:
                mismatches.append({**where, "problem": problem,
                                   "in_call": arguments[check.argument],
                                   "on_record": (answer.get("value") or {}).get(check.field)})
        return {"mismatches": mismatches, "unavailable": unavailable}

    def _decide(self, spec: ToolSpec, facts: Dict[str, Any]):
        verdict, rule, reason = None, None, None
        if self.rules_adapter is not None:
            out = self.rules_adapter.execute({"tool_call": facts})
            if out.get("status") != "success":
                return "hil", None, f"rules engine unavailable: {out.get('error')}"
            decision = out.get("decision") or {}
            if not isinstance(decision, dict):
                decision = {"decision": decision}
            verdict = decision.get("decision")
            rule, reason = decision.get("rule"), decision.get("reason")
            if verdict not in VERDICTS:
                return "hil", rule, f"rules returned {verdict!r}, not allow/deny/hil"

        # The rules can make a call stricter, never looser.
        if facts["mismatches"] or facts["verification_unavailable"]:
            if verdict == "deny":
                return "deny", rule, reason or "denied by the solution's rules"
            what = facts["mismatches"] or facts["verification_unavailable"]
            return "hil", rule, "values don't match the record: " + "; ".join(
                f"{m['argument']} ({m['problem']})" for m in what)
        if verdict in ("deny", "hil"):
            return verdict, rule, reason or f"{verdict} by the solution's rules"
        if spec.irreversible:
            if verdict == "allow" and rule:
                return "allow", rule, reason or f"allowed by rule {rule}"
            why = "not declared, so treated as irreversible" if not spec.declared else "irreversible"
            return "hil", rule, f"{spec.name} is {why} and no rule allows it"
        return "allow", rule, reason or "reversible"

    def _review(self, call: ToolCall, facts: Dict[str, Any], reason: str, expires_at: float) -> Dict[str, Any]:
        """What the person sees, built from the intercepted call (ToolCallApprovalRequest)."""
        return {
            "kind": "tool_call",
            "correlation_id": call.correlation_id,
            "reason": reason,
            "tool": call.tool_name,
            "arguments": call.arguments,
            "call_digest": call.digest(),
            "mismatches": facts["mismatches"],
            "verification_unavailable": facts["verification_unavailable"],
            "irreversible": facts["irreversible"],
            "untrusted_input": facts["untrusted_input"],
            "agent": call.agent_id,
            "request_id": call.request_id,
            "expires_at": expires_at,
            "rationale_untrusted": call.rationale_untrusted,
        }

    async def _run(self, call: ToolCall, connector: Any, spec: ToolSpec, *, decided_by: str) -> Any:
        connector = connector if connector is not None else self._connector_for(spec)
        try:
            with framework_tool_call():
                result = connector.call_tool(call.tool_name, call.arguments)
                if inspect.isawaitable(result):
                    result = await result
        except Exception as exc:
            self.audit.record(call.correlation_id, "failed", {"error": str(exc)[:500], "decided_by": decided_by})
            raise
        self.audit.record(call.correlation_id, "executed", {"decided_by": decided_by})
        return result

    def _connector_for(self, spec: ToolSpec) -> Any:
        if self.connector_resolver is not None:
            return self.connector_resolver(spec)
        if not spec.connector.get("client"):
            raise RuntimeError(f"[ToolGate] cannot run {spec.name} after review: declare "
                               f"security.tool_gate.tools.{spec.name}.connector (client + params)")
        from k9_aif_abb.k9_factories.mcp_client_connection_factory import MCPClientConnectionFactory
        return MCPClientConnectionFactory.get(spec.connector["client"], **dict(spec.connector.get("params") or {}))

    # ------------------------------------------------------------------ resume
    def is_tool_call(self, correlation_id: Optional[str]) -> bool:
        return bool(correlation_id) and self.audit.get_pending(correlation_id) is not None

    async def aresume(self, reply: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a reviewer's reply: run the stored call once on a valid approval, never otherwise."""
        cid = (reply or {}).get("correlation_id")
        pending = self.audit.get_pending(cid) if cid else None
        if pending is None:
            log.warning("[ToolGate] reply for unknown tool call %s: nothing runs", cid)
            return {"status": "not_found", "correlation_id": cid}
        if pending["status"] != "pending":
            return {"status": "already_decided", "correlation_id": cid, "state": pending["status"]}

        spec = self.registry.lookup(pending["call"]["tool_name"])
        decision = ToolCallDecision.parse(
            reply, pending, now=self.clock(), approve_actions=self.approve_actions,
            require_digest_echo=self.require_digest_echo, require_assurance=spec.require_assurance)
        if not decision.approved:
            if self.audit.transition(cid, ["pending"], decision.outcome, decided_by=decision.approver,
                                     decided_at=decision.decided_at, decision_reason=decision.reason):
                self.audit.record(cid, decision.outcome, {"by": decision.approver, "reason": decision.reason})
            return {"status": "not_executed", "outcome": decision.outcome, "reason": decision.reason,
                    "correlation_id": cid}
        return await self._run_approved(pending, decided_by=decision.approver, decided_at=decision.decided_at)

    def resume(self, reply: Dict[str, Any]) -> Dict[str, Any]:
        from k9_aif_abb.k9_core.agent.base_agent import _resolve_sync
        return _resolve_sync(self.aresume(reply))

    async def _run_approved(self, pending: Dict[str, Any], *, decided_by: Optional[str],
                            decided_at: Optional[str]) -> Dict[str, Any]:
        cid = pending["correlation_id"]
        # at most once: claim first; a crash after this never re-runs the call
        if not self.audit.transition(cid, ["pending"], "executing", decided_by=decided_by, decided_at=decided_at):
            return {"status": "already_decided", "correlation_id": cid}
        self.audit.record(cid, "approved", {"by": decided_by, "at": decided_at})
        call = ToolCall.from_dict(pending["call"])
        if call.digest() != pending["digest"]:  # stored call altered after review
            self.audit.transition(cid, ["executing"], "failed", error="stored call does not match its digest")
            self.audit.record(cid, "failed", {"error": "stored call does not match its digest"})
            return {"status": "not_executed", "outcome": "malformed", "correlation_id": cid,
                    "reason": "stored call does not match its digest"}
        spec = self.registry.lookup(call.tool_name)
        connector = self._held_connectors.pop(cid, None)
        try:
            result = await self._run(call, connector, spec, decided_by=decided_by or "reviewer")
        except Exception as exc:
            self.audit.transition(cid, ["executing"], "failed", error=str(exc)[:500])
            raise
        self.audit.transition(cid, ["executing"], "executed")
        return {"status": "executed", "correlation_id": cid, "result": result}

    def expire_stale(self) -> List[Dict[str, Any]]:
        """Apply ``on_expiry`` to reviews past their deadline. Run it on a schedule."""
        out = []
        for pending in self.audit.pending_before(self.clock()):
            cid = pending["correlation_id"]
            if self.on_expiry == "approve":
                log.warning("[ToolGate] review for %s expired; on_expiry=approve runs it unapproved", cid)
                from k9_aif_abb.k9_core.agent.base_agent import _resolve_sync
                out.append(_resolve_sync(self._run_approved(pending, decided_by="on_expiry", decided_at=None)))
            elif self.audit.transition(cid, ["pending"], "expired", decision_reason="deadline passed"):
                self.audit.record(cid, "expired", {"reason": "deadline passed"})
                out.append({"status": "not_executed", "outcome": "expired", "correlation_id": cid})
        return out


def _record_problem(answer: Any, field: str, value: Any) -> Optional[str]:
    """None when the record agrees; 'unavailable' when it can't be relied on; else the mismatch."""
    if not isinstance(answer, dict) or answer.get("refused_by_governance") or answer.get("source_unavailable"):
        return "unavailable"
    flags = answer.get("flags") or {}
    if any(flags.get(k) for k in ("quarantined", "in_review", "conflict", "verification_failed")):
        return "unavailable"
    if not answer.get("found"):
        return "no such record"
    on_record = (answer.get("value") or {}).get(field)
    if on_record is None:
        return f"the record has no {field}"
    return None if str(on_record) == str(value) else "does not match the record"


def _why_unavailable(answer: Any) -> str:
    if not isinstance(answer, dict):
        return "lookup returned no answer"
    if answer.get("refused_by_governance"):
        return f"lookup refused: {answer.get('reason')}"
    if answer.get("source_unavailable"):
        return "system of record unavailable"
    flags = answer.get("flags") or {}
    raised = [k for k in ("quarantined", "in_review", "conflict", "verification_failed") if flags.get(k)]
    return "record flagged: " + ", ".join(raised)


_SHARED_AUDIT: Dict[str, BaseToolCallAuditLog] = {}


def _audit_from_config(cfg: Dict[str, Any]) -> BaseToolCallAuditLog:
    """One audit log per store per process, so the dispatcher an agent holds a call in and
    the one its Orchestrator resumes it with read the same pending calls."""
    audit = cfg.get("audit") or {}
    key = "memory" if audit.get("provider") == "memory" else audit.get("db_path", "./runtime/tool_calls.db")
    if key not in _SHARED_AUDIT:
        _SHARED_AUDIT[key] = (InMemoryToolCallAuditLog() if key == "memory"
                              else SQLiteToolCallAuditLog(key))
    return _SHARED_AUDIT[key]


def reset_shared_audit_logs() -> None:
    """Tests only."""
    _SHARED_AUDIT.clear()
