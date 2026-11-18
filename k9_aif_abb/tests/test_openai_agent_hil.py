# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
OpenAI Agents SDK human-in-the-loop through K9X HIL (1.29.0): BaseHILAdapter / OpenAIHILAdapter,
PausedRunStore, RequiresHIL.resume_state and BaseSquad resuming at the paused step. Driven through the SDK's
real Runner with its ScriptedModel and a real SQLite paused-run store (no network).

Property: a tool marked needs_approval never runs without a person's decision. The run pauses, the reviewer
gets the tool and its arguments (never the SDK's run state), and after the decision the same run continues
where it stopped: approved, the tool runs exactly once; not approved, it never runs and the model is told why.
Steps done before the pause are not run again.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("agents")

from agents.models.interface import ModelProvider  # noqa: E402
from agents.testing import ScriptedModel, assistant_message, function_call  # noqa: E402

from k9_aif_abb.k9_adapters.openai_agents import K9OpenAIAgent, OpenAIHILAdapter  # noqa: E402
from k9_aif_abb.k9_adapters.tool_capability import ToolCapability  # noqa: E402
from k9_aif_abb.k9_core.orchestration.base_hil_adapter import HILDecision  # noqa: E402
from k9_aif_abb.k9_core.orchestration.base_orchestrator import resume_payload_with_state  # noqa: E402
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL  # noqa: E402
from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance  # noqa: E402
from k9_aif_abb.k9_squad.squad_loader import SquadLoader  # noqa: E402
from k9_aif_abb.k9_storage.paused_run_store import PausedRunStore  # noqa: E402
from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage  # noqa: E402

CONFIG = {"security": {"shield": {
    "enabled": True,
    "ingress": {"checks": ["PromptInjectionCheck", "InputSizeCheck"]},
    "egress": {"checks": ["ToolArgumentCheck"]},
}}}
INVOICE = {"vendor": "Acme Supplies", "invoice_id": "INV-1042", "amount": 48500}
REQUEST = {"prompt": "Pay Acme Supplies $48,500 for invoice INV-1042."}


class CheckAgent(K9OpenAIAgent):
    pass


class PaymentAgent(K9OpenAIAgent):
    pass


class _Provider(ModelProvider):
    def __init__(self, model):
        self.model = model

    def get_model(self, model_name):
        return self.model


def _pay_cap(paid):
    async def handler(args):
        paid.append(args)
        return {"status": "paid", **args}
    return ToolCapability(
        name="pay_invoice", description="Pay an approved invoice",
        input_schema={"type": "object", "properties": {"vendor": {"type": "string"},
                                                        "invoice_id": {"type": "string"},
                                                        "amount": {"type": "number"}},
                      "required": ["vendor", "invoice_id", "amount"], "additionalProperties": False},
        handler=handler)


@pytest.fixture
def store(tmp_path):
    return PausedRunStore(SQLiteDatabaseStorage(db_path=str(tmp_path / "paused.db")))


def _squad(tmp_path, model, paid, store, agents=("PaymentAgent",)):
    d = tmp_path / "agents"
    d.mkdir(exist_ok=True)
    (d / "check.yaml").write_text(
        f"class: CheckAgent\nmodule: {__name__}\nname: CheckAgent\nrole: You check the invoice details.\n")
    (d / "payment.yaml").write_text(
        f"class: PaymentAgent\nmodule: {__name__}\nname: PaymentAgent\nrole: You pay approved invoices.\n"
        "tools: [pay_invoice]\nneeds_approval: [pay_invoice]\n")
    flow = "".join(f"      - {{agent: {a}}}\n" for a in agents)
    sq = tmp_path / "squads.yaml"
    sq.write_text(f"squads:\n  ap:\n    agents: [{', '.join(agents)}]\n    flow:\n{flow}")
    loader = SquadLoader.from_agents(d, CONFIG, agent_kwargs={
        "capabilities": [_pay_cap(paid)], "governance": ShieldGovernance(CONFIG),
        "model_routing": "direct", "model_provider": _Provider(model),
        "hil_adapter": OpenAIHILAdapter(store=store, queue="openai-demo")})
    return loader.load_one(sq, "ap")


def _pause(tmp_path, store, paid, agents=("PaymentAgent",), before=()):
    script = [[assistant_message(t)] for t in before] + [
        [function_call("pay_invoice", INVOICE, call_id="c1")]]
    with pytest.raises(RequiresHIL) as exc_info:
        _squad(tmp_path, ScriptedModel(script), paid, store, agents).execute(REQUEST)
    return exc_info.value


def _resume_payload(exc, decision):
    return {**resume_payload_with_state(REQUEST, exc.resume_state), "hil_decision": decision}


def test_needs_approval_pauses_and_the_reviewer_gets_the_call_not_the_run_state(tmp_path, store):
    paid = []
    exc = _pause(tmp_path, store, paid)

    assert paid == []                                                   # nothing ran without a person
    assert exc.queue == "openai-demo" and "PaymentAgent wants to run pay_invoice" in exc.reason
    assert exc.context["tool_calls"] == [{"tool": "pay_invoice", "arguments": INVOICE}]
    key = exc.resume_state["hil_adapter"]["PaymentAgent"]["run_key"]
    saved = store.load(key)
    assert saved and saved["agent"] == "PaymentAgent" and len(saved["state"]) > 100
    assert saved["state"] not in json.dumps(exc.context)                # the reviewer never sees the run state


def test_resume_payload_carries_only_the_key(tmp_path, store):
    exc = _pause(tmp_path, store, [])
    payload = _resume_payload(exc, {"action": "complete", "actor": "demo"})
    text = json.dumps(payload)                                          # persistable as the hil_pending row
    assert "run_key" in text and len(text) < 600


def test_approved_the_same_run_continues_and_the_tool_runs_once(tmp_path, store):
    paid = []
    exc = _pause(tmp_path, store, paid)
    key = exc.resume_state["hil_adapter"]["PaymentAgent"]["run_key"]

    model = ScriptedModel([[assistant_message("Paid INV-1042 to Acme Supplies.")]])
    out = _squad(tmp_path, model, paid, store).execute(_resume_payload(exc, {"action": "complete", "actor": "demo"}))

    assert paid == [INVOICE]                                            # once, with the approved arguments
    assert out["PaymentAgent"]["output"] == "Paid INV-1042 to Acme Supplies."
    assert store.load(key) is None                                      # the paused run is discarded


def test_rejected_the_tool_never_runs_and_the_model_is_told_why(tmp_path, store):
    paid = []
    exc = _pause(tmp_path, store, paid)

    model = ScriptedModel([[assistant_message("Payment not made: not approved.")]])
    decision = {"action": "reject", "actor": "demo", "comment": "Amount over the vendor's limit."}
    out = _squad(tmp_path, model, paid, store).execute(_resume_payload(exc, decision))

    assert paid == []
    seen = str(model.calls[0].input)
    assert "was not approved by demo" in seen and "Amount over the vendor's limit." in seen
    assert out["PaymentAgent"]["output"] == "Payment not made: not approved."


def test_steps_done_before_the_pause_are_not_run_again(tmp_path, store):
    paid = []
    exc = _pause(tmp_path, store, paid, agents=("CheckAgent", "PaymentAgent"),
                 before=["Invoice INV-1042 matches the purchase order."])
    assert "CheckAgent" in exc.resume_state["squad"]["ap"]["results"]

    model = ScriptedModel([[assistant_message("Paid.")]])
    out = _squad(tmp_path, model, paid, store, agents=("CheckAgent", "PaymentAgent")).execute(
        _resume_payload(exc, {"action": "complete", "actor": "demo"}))

    assert len(model.calls) == 1 and "You pay approved invoices." in model.calls[0].system_instructions
    assert out["CheckAgent"]["output"] == "Invoice INV-1042 matches the purchase order."
    assert paid == [INVOICE]


def test_a_resume_whose_paused_run_is_missing_fails_loudly(tmp_path, store):
    exc = _pause(tmp_path, store, [])
    store.discard(exc.resume_state["hil_adapter"]["PaymentAgent"]["run_key"])
    with pytest.raises(RuntimeError, match="was not found"):
        _squad(tmp_path, ScriptedModel([]), [], store).execute(
            _resume_payload(exc, {"action": "complete", "actor": "demo"}))


def test_needs_approval_must_name_a_tool_the_agent_has(tmp_path, store):
    with pytest.raises(ValueError, match="isn't given"):
        PaymentAgent(config={"name": "PaymentAgent", "tools": [], "needs_approval": ["pay_invoice"]},
                     governance=ShieldGovernance(CONFIG), capabilities=[_pay_cap([])])


def test_decision_reads_the_k9x_hil_reply():
    assert HILDecision.from_reply({"action": "complete", "actor": "ravi"}).approved
    rejected = HILDecision.from_reply({"action": "reject", "actor": "ravi", "comment": "No PO."})
    assert not rejected.approved and rejected.rejection_message() == "The request was not approved by ravi. No PO."
    assert "expired" in HILDecision.from_reply({"action": "expire"}).rejection_message()


def test_orchestrator_stores_resume_state_with_the_resume_payload():
    exc = RequiresHIL("x", context={"agent": "A"}, resume_state={"hil_adapter": {"A": {"run_key": "k"}}})
    payload = resume_payload_with_state({"prompt": "p"}, exc.resume_state)
    assert payload == {"prompt": "p", "_k9_resume": {"hil_adapter": {"A": {"run_key": "k"}}}}
    assert resume_payload_with_state({"prompt": "p"}, {}) == {"prompt": "p"}


# ── conditional approval and structured output (accounts payable flow) ────────────────────────────────────

class InvoiceAgent(K9OpenAIAgent):
    pass


def _conditional_payment(store, paid, model):
    return PaymentAgent(
        config={"name": "PaymentAgent", "role": "You pay invoices.", "tools": ["pay_invoice"],
                "needs_approval_when": {"pay_invoice": {"key": "rules_check.output.decision", "eq": "needs_approval"}}},
        governance=ShieldGovernance(CONFIG), capabilities=[_pay_cap(paid)], model_routing="direct",
        model_provider=_Provider(model), hil_adapter=OpenAIHILAdapter(store=store, queue="openai-demo"))


def test_the_tool_pauses_only_when_the_rules_say_so(store):
    paid = []
    auto = _conditional_payment(store, paid, ScriptedModel([
        [function_call("pay_invoice", {**INVOICE, "amount": 900}, call_id="c1")], [assistant_message("Paid.")]]))
    out = auto.execute({**REQUEST, "rules_check": {"output": {"decision": "auto_pay", "rule": "AP-08"}}})
    assert paid == [{**INVOICE, "amount": 900}] and out["output"] == "Paid."     # no person needed

    held = _conditional_payment(store, paid, ScriptedModel([
        [function_call("pay_invoice", INVOICE, call_id="c2")]]))
    with pytest.raises(RequiresHIL):
        held.execute({**REQUEST, "rules_check": {"output": {"decision": "needs_approval", "rule": "AP-07"}}})
    assert len(paid) == 1                                                         # the large one did not run


def test_structured_output_is_returned_as_typed_json(store):
    model = ScriptedModel([[assistant_message(json.dumps({"vendor": "Acme Supplies", "amount": 48500,
                                                         "po_matched": True}))]])
    agent = InvoiceAgent(
        config={"name": "InvoiceAgent", "role": "You read invoices.",
                "structured_output": {"vendor": "string", "amount": "number", "po_matched": "boolean"}},
        governance=ShieldGovernance(CONFIG), model_routing="direct", model_provider=_Provider(model),
        hil_adapter=OpenAIHILAdapter(store=store))
    out = agent.execute({"prompt": "Invoice INV-1042 from Acme Supplies, $48,500, PO 7781."})
    assert json.loads(out["output"]) == {"vendor": "Acme Supplies", "amount": 48500.0, "po_matched": True}
    assert model.calls[0].output_schema is not None                               # the SDK asked for the schema


def test_unknown_structured_output_type_is_refused(store):
    with pytest.raises(ValueError, match="unknown type"):
        InvoiceAgent(config={"name": "InvoiceAgent", "structured_output": {"amount": "money"}},
                     governance=ShieldGovernance(CONFIG), hil_adapter=OpenAIHILAdapter(store=store))
