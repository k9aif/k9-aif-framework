# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""GovernanceEventGate — screen every stream event with the application's governance."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope
from k9_aif_abb.k9_core.streams.event_governance_gate import (
    EventGovernanceGate,
    GateDecision,
    GateResult,
)
from k9_aif_abb.k9_security.tool_result_guard import result_text
from k9_aif_abb.k9_utils.trace_events import emit_trace_event

log = logging.getLogger("governance.event_gate")


class GovernanceEventGate(EventGovernanceGate):
    """
    Stream data is untrusted input: a vendor note, a CRM comment or a ticket body can
    carry instructions planted for whichever agent reads it next (indirect prompt
    injection, OWASP LLM01). This gate runs each event's payload through a governance
    object's ingress stage (``pre_process``) — the same checks an incoming prompt
    gets — before the event reaches live state, a context window or an agent.

    Any governance object works: ``ShieldGovernance`` (deterministic, instant),
    ``GuardianGovernance`` (semantic), or ``ChainedGovernance`` of both. Choose the
    checks for event content — typically ``PromptInjectionCheck`` and
    ``PaymentDiversionCheck``; size or PII checks built for prompts may be stricter
    than a record stream needs.

    PERMIT when governance passes the event; BLOCK (with the governance message as
    the reason) when it raises ``PermissionError``. A failing check never lets an
    event through silently: any other error is a BLOCK too.
    """

    def __init__(self, governance: Any, name: str = "event_gate"):
        if governance is None:
            raise ValueError("GovernanceEventGate needs a governance object (e.g. ShieldGovernance)")
        self.governance = governance
        self.name = name

    def evaluate(self, envelope: EventEnvelope) -> GateResult:
        payload = {"query": result_text(envelope.payload), "source": "stream_event",
                   "event_type": envelope.event_type, "source_system": envelope.source_system}
        ctx: Dict[str, Any] = {"component": f"stream:{envelope.event_type}", "component_type": "event_gate"}
        try:
            outcome = self.governance.pre_process(payload, ctx)
            if inspect.isawaitable(outcome):
                _run_coro_sync(outcome)
        except PermissionError as exc:
            log.warning("[EventGate] BLOCK %s %s: %s", envelope.event_type, envelope.event_id, exc)
            emit_trace_event({"type": "EventGate", "event_type": envelope.event_type, "allowed": False,
                              "reason": str(exc)[:300]})
            return GateResult(GateDecision.BLOCK, envelope, reason=str(exc))
        except Exception as exc:   # a broken check must not wave an event through
            log.error("[EventGate] governance error on %s: %s", envelope.event_type, exc)
            return GateResult(GateDecision.BLOCK, envelope, reason=f"governance error: {exc}")
        emit_trace_event({"type": "EventGate", "event_type": envelope.event_type, "allowed": True})
        return GateResult(GateDecision.PERMIT, envelope)


def _run_coro_sync(coro: Any) -> Any:
    """Same sync bridge as BaseOrchestrator / tool_result_guard: safe inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
