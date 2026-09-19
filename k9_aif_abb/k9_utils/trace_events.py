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
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

_trace_callback: Optional[Callable[[Dict[str, Any]], None]] = None


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
    try:
        _trace_callback(event)
    except Exception as exc:
        log.warning("[trace_events] callback failed: %s", exc)
