# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Who the current call acts for, and which agent is making it (1.36.0).

- ``ACTIVE_CALLER``: the verified caller of the flow this code runs in. Set by
  ``BaseOrchestrator.execute_squads()`` from the signed identity stamp, only
  when ``security.on_behalf_of.enabled``. Never set from self-declared payload
  fields.
- ``ACTIVE_AGENT``: the agent whose governed ``execute()`` this code runs in.
  Set by the ``BaseAgent`` wrapper. Used for the audit record ("agent X, acting
  for John, called the AP MCP server").

Thread bridges in the framework copy the caller's context, so both follow a
sync agent into worker threads and parallel squads.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import List, Optional

ACTIVE_CALLER: contextvars.ContextVar = contextvars.ContextVar("k9_active_caller", default=None)
ACTIVE_AGENT: contextvars.ContextVar = contextvars.ContextVar("k9_active_agent", default=None)


@dataclass(frozen=True)
class CallerContext:
    """The verified person (or service) a flow acts for.

    ``subject_token_ref`` points at the caller's own token in the subject token
    store; None when the caller was authenticated without a bearer token (an
    API key), in which case nothing can be exchanged for them."""
    principal_id: str
    principal_type: str
    roles: List[str] = field(default_factory=list)
    tenant_id: Optional[str] = None
    subject_token_ref: Optional[str] = None
    request_id: Optional[str] = None


def current_caller() -> Optional[CallerContext]:
    return ACTIVE_CALLER.get()


def current_agent() -> Optional[str]:
    return ACTIVE_AGENT.get()


@contextmanager
def caller_scope(caller: Optional[CallerContext]):
    token = ACTIVE_CALLER.set(caller)
    try:
        yield caller
    finally:
        ACTIVE_CALLER.reset(token)


@contextmanager
def agent_scope(agent_name: Optional[str]):
    token = ACTIVE_AGENT.set(agent_name)
    try:
        yield agent_name
    finally:
        ACTIVE_AGENT.reset(token)
