# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
trace_events — shared observability event bus.

One registered callback, called for every LLM call, Shield chain run,
Guardian check, and Zero Trust decision across the framework. An
application registers a sink at startup (e.g. to build a per-request UI
trace, push to Kafka, or export metrics) — nothing is captured or
retained anywhere if no callback is registered.

llm_invoke.py originally had a private, LLM-call-only version of this
(``register_trace_callback`` there). This module generalizes it so
ShieldGovernance/GuardianGovernance/apply_zero_trust can emit through the
same sink — llm_invoke.py now re-exports these two functions for backward
compatibility with existing callers.

Event shapes (``type`` discriminates):
    {"type": "LLMCall",    "agent", "task_type", "model", "provider",
                            "latency_ms", "tokens_in"?, "tokens_out"?}
    {"type": "ShieldChain", "gate": "ingress"|"egress", "agent",
                            "checks": [{"check", "status", "message", "severity"}, ...],
                            "blocked_by": str|None}
    {"type": "ZeroTrust",  "agent", "decision", "allowed", "risk", "reason"}

Every event emitted inside a ``trace_scope()`` also carries ``trace_id`` (1.18.6), so a sink can
stitch one request's model calls, Shield/Guardian checks, tool-result screens, Zero Trust
decisions and Origin answers into one execution path. Orchestrators open the scope in
``execute_squads()`` (and the orchestration adapters in ``execute_flow()``), taking the id from
the payload's ``trace_id``, ``correlation_id`` or ``job_id`` so the path continues across
processes; an application entry point (an API handler) may open its own. Parallel squads run in a
copy of the caller's context, so they share the id.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

log = logging.getLogger(__name__)

_trace_callback: Optional[Callable[[Dict[str, Any]], None]] = None
_TRACE_ID: contextvars.ContextVar = contextvars.ContextVar("k9_trace_id", default=None)

_PAYLOAD_ID_KEYS = ("trace_id", "correlation_id", "job_id")


def current_trace_id() -> Optional[str]:
    """The trace id of the request this code is running for, or None outside any trace_scope()."""
    return _TRACE_ID.get()


def trace_id_from(payload: Any) -> Optional[str]:
    """The id a payload already carries (``trace_id``, ``correlation_id`` or ``job_id``), if any."""
    if isinstance(payload, dict):
        for key in _PAYLOAD_ID_KEYS:
            if payload.get(key):
                return str(payload[key])
    return None


@contextmanager
def trace_scope(trace_id: Optional[str] = None) -> Iterator[str]:
    """Run the block under one trace id. Inside an existing scope the outer id is kept (one request,
    one id), unless the caller passes a different id explicitly. Outside any scope: ``trace_id`` or a
    new random id."""
    outer = _TRACE_ID.get()
    tid = trace_id or outer or uuid.uuid4().hex
    if tid == outer:
        yield tid
        return
    token = _TRACE_ID.set(tid)
    try:
        yield tid
    finally:
        _TRACE_ID.reset(token)


def register_trace_callback(fn: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callback that receives every trace event. Call once at
    application startup. Fire-and-forget: exceptions are caught and logged
    so a failing callback never breaks the caller."""
    global _trace_callback
    _trace_callback = fn
    log.info("[trace_events] callback registered: %s", fn)


def emit_trace_event(event: Dict[str, Any]) -> None:
    """Push one event to the registered callback, if any. Never raises."""
    if _trace_callback is None:
        return
    tid = _TRACE_ID.get()
    if tid and "trace_id" not in event:
        event = {**event, "trace_id": tid}
    try:
        _trace_callback(event)
    except Exception as exc:
        log.warning("[trace_events] callback failed: %s", exc)
