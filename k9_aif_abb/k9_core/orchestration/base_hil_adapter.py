# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseHILAdapter (1.29.0): maps an agent framework's own human-approval pause to K9X HIL, and the decision back.

Agent frameworks pause for a person in their own way: the OpenAI Agents SDK's ``needs_approval`` interruption,
the Claude Agent SDK's tool permission check, LangGraph's interrupts. None of them has a task queue, a sign-in,
roles, deadlines or an audit trail. K9X HIL has all of that. An HIL adapter is the mapping between the two:

- ``adapt_output`` (framework -> K9): the framework's pause becomes a K9X HIL request: what the reviewer sees
  (``describe_pause``) and the framework state, saved in a ``PausedRunStore`` (``serialize_pause``). The agent
  raises the resulting ``RequiresHIL``; only the store key goes into ``resume_state``.
- ``adapt_input`` (K9 -> framework): the K9X HIL reply (``hil_decision`` in the resumed payload) becomes a
  ``HILDecision``, which the implementation applies to the restored framework state.

K9-AIF's HIL rules hold: the agent raises, the squad and orchestrator carry it, only the orchestrator
publishes (``BaseHILOrchestrator``), and the reply comes back through the Router. One implementation per
framework; ``OpenAIHILAdapter`` is the first.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL


@dataclass(frozen=True)
class HILDecision:
    """A person's decision, read from the K9X HIL reply ({correlation_id, action, actor, status, comment, ...})."""

    approved: bool
    action: str
    actor: str
    actor_role: str
    comment: str

    @classmethod
    def from_reply(cls, reply: Dict[str, Any]) -> "HILDecision":
        reply = reply or {}
        action = str(reply.get("action") or "")
        return cls(approved=action == "complete", action=action, actor=str(reply.get("actor") or "the reviewer"),
                   actor_role=str(reply.get("actor_role") or ""), comment=str(reply.get("comment") or ""))

    def rejection_message(self) -> str:
        """What the framework tells its model when the call is not approved."""
        verb = "expired without a decision" if self.action == "expire" else f"was not approved by {self.actor}"
        return f"The request {verb}. {self.comment}".strip()


class BaseHILAdapter(BaseAdapter):
    """Maps one agent framework's approval pause to K9X HIL and back. Subclasses implement the three
    framework-specific methods; the K9 side (RequiresHIL, the reply, the store) is shared."""

    framework: str = "framework"

    def __init__(self, store: Any = None, config: Optional[Dict[str, Any]] = None, *, queue: Optional[str] = None,
                 priority: str = "high", adapter_name: Optional[str] = None) -> None:
        super().__init__(adapter_name=adapter_name)
        self.config = config or {}
        self._store = store
        self.queue = queue
        self.priority = priority

    @property
    def store(self):
        if self._store is None:
            from k9_aif_abb.k9_storage.paused_run_store import PausedRunStore
            self._store = PausedRunStore.from_config(self.config)
        return self._store

    # ── framework-specific ────────────────────────────────────────────────
    @abstractmethod
    def describe_pause(self, pause: Any) -> Dict[str, Any]:
        """What the reviewer sees about the pause (e.g. each tool call and its arguments)."""

    @abstractmethod
    def serialize_pause(self, pause: Any) -> str:
        """The framework's run state as text, so the run can continue later."""

    # (Restoring the state and applying the decision is framework-specific and often async; each
    #  implementation provides its own method for it, e.g. OpenAIHILAdapter.restore().)

    # ── framework -> K9 ───────────────────────────────────────────────────
    def adapt_output(self, result: Any) -> Dict[str, Any]:
        return self.describe_pause(result)

    def pause(self, pause: Any, *, agent: str, request: str, title: Optional[str] = None) -> RequiresHIL:
        """Save the paused state and return the RequiresHIL for the agent to raise."""
        key = self.store.save(self.framework, agent, self.serialize_pause(pause))
        described = self.describe_pause(pause)
        return RequiresHIL(
            reason=title or self.reason_for(agent, described),
            context={"agent": agent, "framework": self.framework, "request": request, **described},
            queue=self.queue, priority=self.priority,
            resume_state={"hil_adapter": {agent: {"framework": self.framework, "run_key": key}}})

    def reason_for(self, agent: str, described: Dict[str, Any]) -> str:
        calls = described.get("tool_calls") or []
        names = ", ".join(str(c.get("tool")) for c in calls) or "an action"
        return f"{agent} wants to run {names}, which needs a person's approval"

    # ── K9 -> framework ───────────────────────────────────────────────────
    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"decision": HILDecision.from_reply((payload or {}).get("hil_decision") or {})}

    def saved_for(self, payload: Dict[str, Any], agent: str) -> Optional[Dict[str, Any]]:
        """The agent's saved pause when this payload resumes it after a decision; None when it doesn't.
        A resume whose saved state is missing raises: the run can't continue, and that must not pass silently."""
        if "hil_decision" not in (payload or {}):
            return None
        ref = ((payload.get("_k9_resume") or {}).get("hil_adapter") or {}).get(agent)
        if not ref:
            return None
        saved = self.store.load(ref["run_key"])
        if saved is None:
            raise RuntimeError(f"[{self.adapter_name}] the paused run {ref['run_key']} for {agent} was not found; "
                               "it can't be resumed")
        return saved

    def finished(self, saved: Dict[str, Any]) -> None:
        self.store.discard(saved["run_key"])
