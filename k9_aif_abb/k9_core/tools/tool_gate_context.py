# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Where a tool call is in the call path, for the tool gate.

- ``ACTIVE_GATE``: the gate session of the governed agent call (or adapter flow)
  this code runs in. ``BaseConnector.call_tool()`` routes through it.
- ``DISPATCHING``: set while the framework itself runs a tool (the dispatcher
  after its decision, or a k9x Origin read-through). Calls made then are not
  gated again.

Thread bridges in the framework copy the caller's context, so the session
follows a sync agent's ``call_tool()`` into the worker thread. If it is ever
missing while a gate is enabled in this process, the call is refused in
production rather than run ungated (``gate_required()``).
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, List, Optional

log = logging.getLogger("k9.tool_gate")

ACTIVE_GATE: contextvars.ContextVar = contextvars.ContextVar("k9_tool_gate", default=None)
DISPATCHING: contextvars.ContextVar = contextvars.ContextVar("k9_tool_dispatching", default=False)

_GATE_REQUIRED = False
_UNGATED_WARNED = False


def require_gate() -> None:
    """Called when a gate is enabled anywhere in this process: from now on a tool call
    that arrives with no gate session is refused in production."""
    global _GATE_REQUIRED
    _GATE_REQUIRED = True


def gate_required() -> bool:
    return _GATE_REQUIRED


def warn_ungated_once(connector: str, tool_name: str) -> None:
    global _UNGATED_WARNED
    if not _UNGATED_WARNED:
        _UNGATED_WARNED = True
        log.warning("[ToolGate] tool %r called through %s with no tool gate (security.tool_gate.enabled "
                    "is off): irreversible calls run without review. The gate is the default in 2.0.",
                    tool_name, connector)


@dataclass
class GateSession:
    """One governed agent call (or adapter flow) under a tool gate."""
    dispatcher: Any
    agent_id: Optional[str] = None
    request_id: Optional[str] = None
    untrusted_input: bool = True
    pending: List[Any] = field(default_factory=list)   # reviews raised in this call
    parent: Optional["GateSession"] = None              # the enclosing agent call, if nested

    def hold(self, review: Any) -> None:
        """Remember a review raised in this call and in every enclosing one, so whichever
        agent's code catches it, the governed wrapper around it raises it again."""
        session: Optional[GateSession] = self
        while session is not None:
            session.pending.append(review)
            session = session.parent


@contextmanager
def gate_session(session: Optional[GateSession]):
    token = ACTIVE_GATE.set(session)
    try:
        yield session
    finally:
        ACTIVE_GATE.reset(token)


@contextmanager
def framework_tool_call():
    """The framework itself is running a tool: don't gate it again. Framework code only."""
    token = DISPATCHING.set(True)
    try:
        yield
    finally:
        DISPATCHING.reset(token)
