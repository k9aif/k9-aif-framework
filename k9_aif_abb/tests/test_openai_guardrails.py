# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
The OpenAI Agents SDK's own agent guardrails under K9-AIF (1.35.0), through the SDK's real Runner and its
ScriptedModel (no network).

Property: a developer's own SDK guardrail runs under K9-AIF as it does in the SDK, beside K9's checks, and
its tripwire becomes a K9-AIF signal: ``PermissionError`` (like a k9x Shield block) by default, or
``RequiresHIL`` for a person's review (``on_trip: hil``). After an approved review the run starts again
without that guardrail; a rejected one ends with ``PermissionError``. A guardrail the SDK would never run is
refused at construction, never silently ignored.
"""

from __future__ import annotations

import pytest

pytest.importorskip("agents")

from agents import GuardrailFunctionOutput, input_guardrail, output_guardrail  # noqa: E402
from agents.models.interface import ModelProvider  # noqa: E402
from agents.testing import ScriptedModel, assistant_message  # noqa: E402

from k9_aif_abb.k9_adapters.openai_agents import K9OpenAIAgent  # noqa: E402
from k9_aif_abb.k9_adapters.openai_agents.k9_openai_agents_adapter import K9OpenAIAgentsAdapter  # noqa: E402
from k9_aif_abb.k9_core.orchestration.base_orchestrator import resume_payload_with_state  # noqa: E402
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL  # noqa: E402
from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance  # noqa: E402

CONFIG = {"security": {"shield": {"enabled": True, "ingress": {"checks": ["PromptInjectionCheck"]},
                                  "egress": {"checks": ["ToolArgumentCheck"]}}}}
M = __name__


# ── the developer's own guardrails (plain SDK code) ──────────────────────────────────────────────────────

@input_guardrail(run_in_parallel=False)
async def churn_tripwire(ctx, agent, input):
    risk = "cancel" in str(input).lower()
    return GuardrailFunctionOutput(output_info={"is_churn_risk": risk, "reasoning": "mentions cancelling" if risk
                                                else "no churn signal"}, tripwire_triggered=risk)


async def plain_blocklist(ctx, agent, input):          # undecorated: K9-AIF wraps it as an input guardrail
    return GuardrailFunctionOutput(output_info={"reason": "blocked word"},
                                   tripwire_triggered="forbidden" in str(input).lower())


@output_guardrail
async def no_refund_promises(ctx, agent, output):
    return GuardrailFunctionOutput(output_info={"reason": "promised a refund"},
                                   tripwire_triggered="refund" in str(output).lower())


class SupportAgent(K9OpenAIAgent):
    pass


class _Provider(ModelProvider):
    def __init__(self, model):
        self.model = model

    def get_model(self, model_name):
        return self.model


def _agent(model, **yaml):
    config = {"name": "SupportAgent", "role": "You are a customer support agent.", **yaml}
    return SupportAgent(config=config, governance=ShieldGovernance(CONFIG), model_routing="direct",
                        model_provider=_Provider(model))


def _reply(text):
    return ScriptedModel([[assistant_message(text)]])


CHURN_HIL = [{"function": "churn_tripwire", "module": M, "on_trip": "hil", "hil_queue": "retention"}]


# ── squad step (K9OpenAIAgent) ───────────────────────────────────────────────────────────────────────────

def test_a_passing_guardrail_lets_the_agent_answer():
    out = _agent(_reply("Hello! How can I help?"), input_guardrails=CHURN_HIL).execute({"prompt": "Hello!"})
    assert out["output"] == "Hello! How can I help?"


def test_a_tripwire_blocks_by_default_like_shield():
    model = _reply("never seen")
    agent = _agent(model, input_guardrails=[{"function": "churn_tripwire", "module": M}])
    with pytest.raises(PermissionError, match="churn_tripwire tripped: mentions cancelling"):
        agent.execute({"prompt": "I think I might cancel my subscription"})
    assert model.calls == ()                                  # run_in_parallel=False: the agent never started


def test_a_plain_function_is_wrapped_as_a_guardrail():
    agent = _agent(_reply("x"), input_guardrails=[{"function": "plain_blocklist", "module": M}])
    with pytest.raises(PermissionError, match="plain_blocklist"):
        agent.execute({"prompt": "say the forbidden word"})


def test_on_trip_hil_opens_a_case_on_the_queue():
    agent = _agent(_reply("never seen"), input_guardrails=CHURN_HIL)
    with pytest.raises(RequiresHIL) as exc:
        agent.execute({"prompt": "I think I might cancel my subscription"})
    assert exc.value.queue == "retention"
    assert exc.value.context["guardrail"] == "churn_tripwire"
    assert exc.value.context["output_info"]["is_churn_risk"] is True
    assert exc.value.resume_state == {"guardrail": {"SupportAgent": "churn_tripwire"}}


def _resumed(exc, action):
    payload = {"prompt": "I think I might cancel my subscription"}
    return {**resume_payload_with_state(payload, exc.resume_state),
            "hil_decision": {"action": action, "actor": "pat"}}


def test_after_approval_the_run_starts_again_without_that_guardrail():
    with pytest.raises(RequiresHIL) as exc:
        _agent(_reply("x"), input_guardrails=CHURN_HIL).execute({"prompt": "I think I might cancel my subscription"})
    agent = _agent(_reply("I'm sorry to hear that. Let me help."), input_guardrails=CHURN_HIL)
    out = agent.execute(_resumed(exc.value, "complete"))
    assert out["output"] == "I'm sorry to hear that. Let me help."
    assert [g.get_name() for g in agent._agent.input_guardrails] == ["churn_tripwire"]   # only that run skipped it


def test_after_rejection_the_run_ends():
    with pytest.raises(RequiresHIL) as exc:
        _agent(_reply("x"), input_guardrails=CHURN_HIL).execute({"prompt": "I think I might cancel my subscription"})
    model = _reply("never seen")
    with pytest.raises(PermissionError, match="was not approved by pat"):
        _agent(model, input_guardrails=CHURN_HIL).execute(_resumed(exc.value, "reject"))
    assert model.calls == ()


def test_an_output_guardrail_blocks_the_answer():
    agent = _agent(_reply("Sure, you'll get a full refund."),
                   output_guardrails=[{"function": "no_refund_promises", "module": M}])
    with pytest.raises(PermissionError, match="output guardrail no_refund_promises tripped"):
        agent.execute({"prompt": "Can I get my money back?"})


@pytest.mark.parametrize("yaml, error", [
    ({"output_guardrails": [{"function": "no_refund_promises", "module": M, "on_trip": "hil"}]}, "for input guardrails"),
    ({"input_guardrails": [{"function": "no_refund_promises", "module": M}]}, "is an output guardrail"),
    ({"input_guardrails": [{"function": "churn_tripwire", "module": M, "on_trip": "ask"}]}, "on_trip must be"),
    ({"input_guardrails": [{"function": "missing", "module": M}]}, "has no missing"),
    ({"input_guardrails": [{"function": "churn_tripwire"}]}, "needs 'function' and 'module'"),
    ({"input_guardrails": [{"function": "churn_tripwire", "module": M},
                           {"function": "churn_tripwire", "module": M}]}, "used twice"),
])
def test_a_bad_entry_fails_when_the_agent_is_built(yaml, error):
    with pytest.raises((ValueError, ImportError), match=error):
        _agent(_reply("x"), **yaml)


# ── orchestrator adapter (handoffs / manager) ────────────────────────────────────────────────────────────

def _spec(name, **extra):
    return {"name": name, "description": name, "role": "You help.", "model": "m", "tools": [], "handoffs": [],
            **extra}


def _adapter(model, specs, entry="Front"):
    return K9OpenAIAgentsAdapter(capabilities=[], agents=specs, entry_agent=entry, config=CONFIG,
                                 governance=ShieldGovernance(CONFIG), model_routing="direct",
                                 model_provider=_Provider(model))


def test_adapter_entry_agent_guardrail_blocks():
    adapter = _adapter(_reply("never seen"),
                       {"Front": _spec("Front", input_guardrails=[{"function": "churn_tripwire", "module": M}])})
    with pytest.raises(PermissionError, match="churn_tripwire tripped"):
        adapter.execute({"message": "I want to cancel"})


def test_adapter_review_then_approval_runs_without_the_guardrail():
    specs = {"Front": _spec("Front", input_guardrails=CHURN_HIL)}
    with pytest.raises(RequiresHIL) as exc:
        _adapter(_reply("x"), specs).execute({"message": "I want to cancel"})
    assert exc.value.resume_state == {"guardrail": {"OpenAIAgentsOrchestratorAdapter": "churn_tripwire"}}
    resumed = {**resume_payload_with_state({"message": "I want to cancel"}, exc.value.resume_state),
               "hil_decision": {"action": "complete", "actor": "pat"}}
    out = _adapter(_reply("Let me help you with that."), specs).execute(resumed)
    assert out["output_text"] == "Let me help you with that."


def test_adapter_refuses_input_guardrails_the_sdk_would_never_run():
    specs = {"Front": _spec("Front", handoffs=["Orders"]),
             "Orders": _spec("Orders", input_guardrails=[{"function": "churn_tripwire", "module": M}])}
    with pytest.raises(ValueError, match="would never run"):
        _adapter(_reply("x"), specs)


def test_adapter_hil_is_for_the_entry_agent():
    specs = {"Front": _spec("Front", agent_tools=["Spanish"]),
             "Spanish": _spec("Spanish", input_guardrails=CHURN_HIL)}
    with pytest.raises(ValueError, match="entry agent"):
        _adapter(_reply("x"), specs)


# ── a guardrail that runs an agent of its own (the guide's churn check) ──────────────────────────────────

from agents import Agent, Runner  # noqa: E402

from k9_aif_abb.k9_adapters.openai_agents import current_run_config  # noqa: E402

check_agent = Agent(name="Churn Detection Agent", instructions="Is this a churn risk? Answer yes or no.")


@input_guardrail(run_in_parallel=False)
async def agent_backed_tripwire(ctx, agent, input):
    result = await Runner.run(check_agent, input, context=ctx.context, run_config=current_run_config())
    return GuardrailFunctionOutput(output_info={"reasoning": result.final_output},
                                   tripwire_triggered=result.final_output.strip().lower() == "yes")


def test_a_guardrail_agent_uses_the_runs_provider():
    model = ScriptedModel([[assistant_message("yes")], [assistant_message("never seen")]])
    agent = _agent(model, input_guardrails=[{"function": "agent_backed_tripwire", "module": M}])
    with pytest.raises(PermissionError, match="agent_backed_tripwire tripped: yes"):
        agent.execute({"prompt": "I think I might cancel"})
    assert len(model.calls) == 1                  # the check's model call went through the run's provider


def test_current_run_config_outside_a_run_refuses():
    with pytest.raises(RuntimeError, match="no K9-governed OpenAI run"):
        current_run_config()
