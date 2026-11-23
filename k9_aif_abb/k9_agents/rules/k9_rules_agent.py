# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""K9RulesAgent — the business-rules step of a squad."""

from __future__ import annotations

from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_core.governance.base_rules_agent import BaseRulesAgent
from k9_aif_abb.k9_core.orchestration.base_hil_adapter import HILDecision
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_core.orchestration.hil_task import ROLES


class K9RulesAgent(BaseRulesAgent):
    """
    Business decisions stay out of data access: k9x Origin supplies facts, this step decides.
    It evaluates the payload (including ``live_context``) with a rules adapter (the built-in
    ``K9RulesAdapter``, a ``RestRulesAdapter`` decision service, or any ``BaseRulesAdapter``) and:

    - ``hil`` (or any decision in ``hil_decisions``) → raises ``RequiresHIL`` with the rule and
      its reason; the Orchestrator opens a K9X HIL case and the flow resumes on the decision;
    - any other decision → returns ``{"output": {"decision", "rule", "reason"}}`` for the next
      step (``hold``, ``allow``, or your own).
    - resumed after the person decided (1.35.0) → returns the person's decision
      (``approved`` / ``rejected``, ``decided_by``, ``comment``) instead of raising the same case again.

    Config::

        rules_agent:
          adapter: k9_rules                 # name in IntegrationAdapterFactory
          hil_queue: claims-review
          rules:
            - {name: large claim, when: "claim.amount > 5000", then: hil}
            - {name: data conflict, when: "live_context.*.flags.conflict", then: hil}
    """

    layer = "K9RulesAgent"

    def __init__(self, config: Optional[Dict[str, Any]] = None, governance: Any = None,
                 adapter: Any = None, monitor: Any = None):
        BaseAgent.__init__(self, config or {}, monitor=monitor, governance=governance)
        cfg = (self.config.get("rules_agent") or {})
        if adapter is None:
            from k9_aif_abb.k9_adapters.integration import IntegrationAdapterFactory
            adapter = IntegrationAdapterFactory.get(cfg.get("adapter", "k9_rules"),
                                                    {k: v for k, v in cfg.items() if k != "adapter"})
        self.adapter = adapter
        self.hil_decisions = set(cfg.get("hil_decisions") or ["hil"])
        self.hil_queue = cfg.get("hil_queue")

    @property
    def _step_name(self) -> str:
        return str(self.config.get("name") or type(self).__name__)

    def _resume_state(self, rule: Any) -> Dict[str, Any]:
        return {"rules_agent": {self._step_name: {"rule": rule}}}

    def person_decision(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """(1.35.0) When ``request`` resumes this step after a person decided its case in K9X HIL: the
        person's decision as this step's output, instead of evaluating the rules again (which would only
        raise the same case again). ``decision`` is ``approved`` or ``rejected``; a later step's ``when:``
        reads it. None when the request isn't such a resume."""
        if "hil_decision" not in (request or {}):
            return None
        saved = ((request.get("_k9_resume") or {}).get("rules_agent") or {}).get(self._step_name)
        if saved is None:
            return None
        decision = HILDecision.from_reply(request.get("hil_decision") or {})
        verdict = "approved" if decision.approved else "rejected"
        return {"output": {"decision": verdict, "rule": saved.get("rule"),
                           "reason": f"rule {saved.get('rule')}: {verdict} by {decision.actor}",
                           "decided_by": decision.actor, "comment": decision.comment}}

    def evaluate_rules(self, request: Dict[str, Any]) -> Dict[str, Any]:
        decided = self.person_decision(request)
        if decided is not None:
            return decided
        out = self.adapter.execute(request)
        if out.get("status") != "success":
            # a rules engine that cannot answer must not wave a decision through
            raise RequiresHIL(f"rules engine unavailable: {out.get('error')}", context={"adapter": out.get("adapter")},
                              queue=self.hil_queue, priority="high", resume_state=self._resume_state(None))
        decision = out.get("decision") or {}
        if not isinstance(decision, dict):
            decision = {"decision": decision}
        verdict = str(decision.get("decision", "allow"))
        if verdict in self.hil_decisions:
            role = decision.get("approver_role")
            raise RequiresHIL(decision.get("reason") or f"rule {decision.get('rule')}",
                              context={"rule": decision.get("rule"), "decision": verdict},
                              queue=self.hil_queue, task_type="rules-decision",
                              required_role=role if role in ROLES else None,
                              resume_state=self._resume_state(decision.get("rule")))
        # 1.30.0: every field the rules returned (e.g. approver_role), not only decision, rule and reason
        return {"output": {**decision, "decision": verdict, "rule": decision.get("rule"),
                           "reason": decision.get("reason")}}
