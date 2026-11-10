# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ToolCallDecision: reads a reviewer's reply to a pending tool call, strictly.

The reply is the HIL wire format k9x-hil publishes on ``hil.replies.<queue>``:
``{correlation_id, action, actor, status, comment, result, decided_at}``.

Only one thing counts as approval: an approving ``action`` (``complete`` by
default) for this ``correlation_id``, from a named ``actor``, before the call's
deadline, with no ``result.approved: false``, and, when the reply carries a
``result.call_digest``, a digest equal to the reviewed call's. Everything else
(``reject``, ``expire``, an unknown action, a missing actor, a late reply, a
digest that doesn't match) means the call does not run.

The approved call is always the one stored when it was intercepted, never one
re-proposed later, so an approval can only run what the reviewer saw.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

DEFAULT_APPROVE_ACTIONS = ("complete",)


@dataclass(frozen=True)
class ToolCallDecision:
    approved: bool
    outcome: str            # approved | rejected | expired | malformed
    reason: str
    approver: Optional[str] = None
    decided_at: Optional[str] = None

    @classmethod
    def parse(cls, reply: Any, pending: Dict[str, Any], *, now: Optional[float] = None,
              approve_actions: Iterable[str] = DEFAULT_APPROVE_ACTIONS,
              require_digest_echo: bool = False,
              require_assurance: Iterable[str] = ()) -> "ToolCallDecision":
        now = time.time() if now is None else now
        if not isinstance(reply, dict):
            return cls(False, "malformed", "reply is not an object")
        if reply.get("correlation_id") != pending.get("correlation_id"):
            return cls(False, "malformed", "reply is for a different call")

        action = reply.get("action")
        actor = reply.get("actor") or None
        decided_at = reply.get("decided_at")
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}

        expires_at = pending.get("expires_at")
        if expires_at is not None and now > float(expires_at):
            return cls(False, "expired", "the reply arrived after the deadline", actor, decided_at)
        if action == "expire":
            return cls(False, "expired", "the review expired", actor, decided_at)
        if action == "reject":
            return cls(False, "rejected", reply.get("comment") or "rejected by the reviewer", actor, decided_at)
        if action not in set(approve_actions):
            return cls(False, "malformed", f"unknown action {action!r}", actor, decided_at)
        if not actor:
            return cls(False, "malformed", "approval names no reviewer", None, decided_at)
        if result.get("approved") is False:
            return cls(False, "rejected", "the reviewer completed the task without approving", actor, decided_at)

        echoed = result.get("call_digest")
        if echoed is not None and echoed != pending.get("digest"):
            return cls(False, "malformed", "the approval is for a different call (digest mismatch)", actor, decided_at)
        if require_digest_echo and echoed is None:
            return cls(False, "malformed", "the approval does not name the call it approves", actor, decided_at)

        needed = set(require_assurance)
        if needed:
            have = set(result.get("assurance") or reply.get("assurance") or [])
            if not needed <= have:
                return cls(False, "malformed",
                           f"the reviewer's sign-in lacks {sorted(needed - have)}", actor, decided_at)

        return cls(True, "approved", "approved by the reviewer", actor, decided_at)
