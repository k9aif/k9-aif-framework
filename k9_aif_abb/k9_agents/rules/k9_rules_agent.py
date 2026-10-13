# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""K9RulesAgent — the business-rules step of a squad."""

from __future__ import annotations

from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_core.governance.base_rules_agent import BaseRulesAgent
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL


class K9RulesAgent(BaseRulesAgent):
    """
    Business decisions stay out of data access: k9x Origin supplies facts, this step decides.
    It evaluates the payload (including ``live_context``) with a rules adapter (the built-in
    ``K9RulesAdapter``, a ``RestRulesAdapter`` decision service, or any ``BaseRulesAdapter``) and:

    - ``hil`` (or any decision in ``hil_decisions``) → raises ``RequiresHIL`` with the rule and
      its reason; the Orchestrator opens a K9X HIL case and the flow resumes on the decision;
    - any other decision → returns ``{"output": {"decision", "rule", "reason"}}`` for the next
      step (``hold``, ``allow``, or your own).

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

    def evaluate_rules(self, request: Dict[str, Any]) -> Dict[str, Any]:
        out = self.adapter.execute(request)
        if out.get("status") != "success":
            # a rules engine that cannot answer must not wave a decision through
            raise RequiresHIL(f"rules engine unavailable: {out.get('error')}", context={"adapter": out.get("adapter")},
                              queue=self.hil_queue, priority="high")
        decision = out.get("decision") or {}
        if not isinstance(decision, dict):
            decision = {"decision": decision}
        verdict = str(decision.get("decision", "allow"))
        if verdict in self.hil_decisions:
            raise RequiresHIL(decision.get("reason") or f"rule {decision.get('rule')}",
                              context={"rule": decision.get("rule"), "decision": verdict},
                              queue=self.hil_queue)
        return {"output": {"decision": verdict, "rule": decision.get("rule"), "reason": decision.get("reason")}}
