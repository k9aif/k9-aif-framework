# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Conditions read inside structured output (1.35.0).

Property: a squad's ``when:`` and a rule's ``when`` can test a field of an earlier step's structured
output, although that output travels as JSON text; and a squad can mix OpenAI agents with a
``K9RulesAgent`` without a subclass. Before 1.35.0 the condition stopped at the text and found
nothing (a rule never matched, a ``when:`` never held), and ``SquadLoader`` handed the rules agent
the OpenAI agents' keywords, which raised ``TypeError``.

The end-to-end case is OpenAI's own guardrail example (A practical guide to building agents,
pp. 28-29): a churn check before the customer-support agent. Under K9-AIF the decision is a rule,
and a churn risk goes to a person on the retention queue.
"""

from __future__ import annotations

import json

import pytest

from k9_aif_abb.k9_adapters.integration.k9_rules_adapter import K9RulesAdapter
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_squad.base_squad import _eval_when
from k9_aif_abb.k9_utils.step_outputs import parse_json_text, resolve_path, with_parsed_outputs

CHURN = {"output": json.dumps({"is_churn_risk": True, "reasoning": "mentions cancelling"}), "agent": "Churn"}
CALM = {"output": json.dumps({"is_churn_risk": False, "reasoning": "a greeting"}), "agent": "Churn"}


# ── the helper ────────────────────────────────────────────────────────────────────────────────────────────

def test_only_json_objects_and_lists_are_parsed():
    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text("[1, 2]") == [1, 2]
    for unchanged in ("plain text", "42", "true", "{not json", "", None, 7, {"a": 1}):
        assert parse_json_text(unchanged) == unchanged


def test_a_path_continues_inside_json_text_and_lists():
    ctx = {"churn": CHURN, "inv": {"output": json.dumps({"lines": [{"amount": 5}]})}}
    assert resolve_path(ctx, "churn.output.is_churn_risk") is True
    assert resolve_path(ctx, "inv.output.lines.0.amount") == 5
    assert resolve_path(ctx, "churn.output") == CHURN["output"]          # the text itself, unchanged
    assert resolve_path(ctx, "churn.output.missing") is None
    assert resolve_path({"note": {"output": "plain"}}, "note.output.x") is None


def test_parsed_outputs_leave_the_payload_alone():
    payload = {"churn": CHURN, "prompt": "hi"}
    parsed = with_parsed_outputs(payload)
    assert parsed["churn"]["output"]["is_churn_risk"] is True
    assert isinstance(payload["churn"]["output"], str)                    # stored result still text
    assert parsed["prompt"] == "hi"


# ── squad when: and rules ─────────────────────────────────────────────────────────────────────────────────

def test_squad_when_reads_a_structured_field():
    when = {"key": "churn.output.is_churn_risk", "ne": True}
    assert _eval_when(when, {"churn": CHURN}) is False
    assert _eval_when(when, {"churn": CALM}) is True


def test_a_plain_text_output_compares_as_before():
    assert _eval_when({"key": "step.output", "eq": "done"}, {"step": {"output": "done"}}) is True


RULES = {"rules": [{"name": "churn risk", "when": "churn.output.is_churn_risk == true", "then": "hil",
                    "reason": "the customer may cancel; a retention specialist answers"}]}


def test_a_rule_matches_a_structured_field():
    out = K9RulesAdapter(RULES).execute({"churn": CHURN})
    assert out["status"] == "success" and out["decision"]["decision"] == "hil"
    assert K9RulesAdapter(RULES).execute({"churn": CALM})["decision"]["decision"] == "allow"


def test_every_rules_engine_gets_the_parsed_facts():
    from k9_aif_abb.k9_adapters.integration.base_rules_adapter import BaseRulesAdapter

    seen = {}

    class Engine(BaseRulesAdapter):
        def evaluate(self, ruleset, facts):
            seen.update(facts)
            return {"decision": "allow"}

    payload = {"churn": CHURN}
    Engine({}).execute(payload)
    assert seen["churn"]["output"]["is_churn_risk"] is True              # a decision service sees fields
    assert isinstance(payload["churn"]["output"], str)


# ── end to end: OpenAI's churn example as a K9-AIF squad ──────────────────────────────────────────────────

agents_sdk = pytest.importorskip("agents")

from agents.models.interface import ModelProvider  # noqa: E402
from agents.testing import ScriptedModel, assistant_message  # noqa: E402

from k9_aif_abb.k9_adapters.openai_agents import K9OpenAIAgent  # noqa: E402
from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance  # noqa: E402
from k9_aif_abb.k9_squad.squad_loader import SquadLoader  # noqa: E402

CONFIG = {"security": {"shield": {"enabled": True, "ingress": {"checks": ["PromptInjectionCheck"]},
                                  "egress": {"checks": ["ToolArgumentCheck"]}}}}


class ChurnDetectionAgent(K9OpenAIAgent):
    pass


class CustomerSupportAgent(K9OpenAIAgent):
    pass


class _Provider(ModelProvider):
    def __init__(self, model):
        self.model = model

    def get_model(self, model_name):
        return self.model


SQUADS = """squads:
  customer_support:
    description: OpenAI's churn guardrail, as a K9-AIF squad
    agents: [ChurnDetectionAgent, K9RulesAgent, CustomerSupportAgent]
    flow:
      - {agent: ChurnDetectionAgent, result_key: churn}
      - {agent: K9RulesAgent, result_key: churn_rules}
      - {agent: CustomerSupportAgent, result_key: answer}
"""

AGENTS = {
    "ChurnDetectionAgent": f"""class: ChurnDetectionAgent
module: {__name__}
name: ChurnDetectionAgent
role: Identify if the user message indicates a potential customer churn risk.
structured_output:
  is_churn_risk: boolean
  reasoning: string
""",
    # the framework's own class, no subclass: the loader no longer hands it the OpenAI keywords
    "K9RulesAgent": """class: K9RulesAgent
module: k9_aif_abb.k9_agents.rules.k9_rules_agent
name: ChurnRules
rules_agent:
  adapter: k9_rules
  hil_queue: retention
  rules:
    - name: churn risk
      when: "churn.output.is_churn_risk == true"
      then: hil
      reason: the customer may cancel; a retention specialist answers
""",
    "CustomerSupportAgent": f"""class: CustomerSupportAgent
module: {__name__}
name: CustomerSupportAgent
role: You are a customer support agent. You help customers with their questions.
""",
}


def _squad(tmp_path, model):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for name, body in AGENTS.items():
        (agents_dir / f"{name}.yaml").write_text(body, encoding="utf-8")
    squads = tmp_path / "squads.yaml"
    squads.write_text(SQUADS, encoding="utf-8")
    loader = SquadLoader.from_agents(agents_dir, CONFIG, agent_kwargs={
        "governance": ShieldGovernance(CONFIG), "model_routing": "direct", "model_provider": _Provider(model)})
    return loader.load_one(squads, "customer_support")


def test_a_churn_risk_goes_to_a_person_and_the_support_agent_never_runs(tmp_path):
    model = ScriptedModel([[assistant_message(json.dumps({"is_churn_risk": True,
                                                          "reasoning": "says they might cancel"}))]])
    squad = _squad(tmp_path, model)
    with pytest.raises(RequiresHIL) as exc:
        squad.execute({"prompt": "I think I might cancel my subscription"})
    assert exc.value.queue == "retention"
    assert len(model.calls) == 1                                          # the support agent never ran


def test_a_normal_message_is_answered(tmp_path):
    model = ScriptedModel([
        [assistant_message(json.dumps({"is_churn_risk": False, "reasoning": "a greeting"}))],
        [assistant_message("Hello! How can I help you today?")],
    ])
    out = _squad(tmp_path, model).execute({"prompt": "Hello!"})
    results = out.get("results", out)
    assert results["churn_rules"]["output"]["decision"] == "allow"
    assert results["answer"]["output"] == "Hello! How can I help you today?"
