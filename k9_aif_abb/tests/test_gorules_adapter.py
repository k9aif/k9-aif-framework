# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
GoRulesAdapter (1.29.0): K9RulesAgent decides through a GoRules decision service.

Property: the decision comes from the rules engine, never from the payload or a model: the adapter sends the
facts to the decision model and returns its result; K9RulesAgent passes the decision on, and an engine that
can't answer never waves a decision through. The live test runs against a real GoRules agent when
K9_TEST_GORULES_URL is set (k9x-ecosystem/k9x_rules_engine, accounts-payable/invoice-approval.json).
"""

from __future__ import annotations

import json
import os

import pytest

from k9_aif_abb.k9_adapters.integration import GoRulesAdapter, IntegrationAdapterFactory
from k9_aif_abb.k9_agents.rules.k9_rules_agent import K9RulesAgent
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL

CFG = {"engine_url": "http://rules.test", "project": "accounts-payable", "ruleset": "invoice-approval.json",
       "facts": "invoice_agent.output"}
INVOICE = {"vendor": "Acme Supplies", "vendor_status": "approved", "amount": 48500, "duplicate": False,
           "bank_changed": False, "po_matched": True}


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


@pytest.fixture
def engine(monkeypatch):
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        amount = (json or {}).get("context", {}).get("amount", 0)
        result = ({"decision": "needs_approval", "rule": "AP-07", "reason": "over $15,000", "approver_role": "worker"}
                  if amount > 15000 else {"decision": "auto_pay", "rule": "AP-08", "reason": "within limit"})
        return _Resp({"performance": "1ms", "result": result})

    import requests
    monkeypatch.setattr(requests, "post", post)
    return calls


def test_registered_as_gorules():
    assert isinstance(IntegrationAdapterFactory.get("gorules", CFG), GoRulesAdapter)


def test_posts_the_facts_to_the_decision_model_and_returns_its_result(engine):
    out = GoRulesAdapter(CFG).execute({"invoice_agent": {"output": json.dumps(INVOICE)}})
    assert engine[0]["url"] == "http://rules.test/api/projects/accounts-payable/evaluate/invoice-approval.json"
    assert engine[0]["json"] == {"context": INVOICE}                 # structured output JSON text, parsed
    assert out["status"] == "success" and out["decision"]["rule"] == "AP-07"


def test_rules_agent_passes_the_engine_decision_on(engine):
    agent = K9RulesAgent(config={"rules_agent": {"adapter": "gorules", **CFG}})
    small = agent.evaluate_rules({"invoice_agent": {"output": {**INVOICE, "amount": 900}}})
    big = agent.evaluate_rules({"invoice_agent": {"output": INVOICE}})
    assert small["output"] == {"decision": "auto_pay", "rule": "AP-08", "reason": "within limit"}
    assert big["output"]["decision"] == "needs_approval" and big["output"]["rule"] == "AP-07"


def test_an_engine_that_cannot_answer_never_waves_a_decision_through(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp({"message": "Project not found"}, 404))
    agent = K9RulesAgent(config={"rules_agent": {"adapter": "gorules", **CFG}})
    with pytest.raises(RequiresHIL, match="rules engine unavailable"):
        agent.evaluate_rules({"invoice_agent": {"output": INVOICE}})


def test_missing_facts_are_an_error_not_an_empty_context(engine):
    out = GoRulesAdapter(CFG).execute({"something_else": 1})
    assert out["status"] == "error" and "no facts" in out["error"] and engine == []


LIVE = os.environ.get("K9_TEST_GORULES_URL")
CASES = [
    ({"vendor_status": "blocked", "amount": 500}, "reject", "AP-01"),
    ({"duplicate": True, "amount": 500}, "reject", "AP-02"),
    ({"amount": 150000}, "needs_approval", "AP-03"),
    ({"bank_changed": True, "amount": 900}, "needs_approval", "AP-04"),
    ({"vendor_status": "new", "amount": 900}, "needs_approval", "AP-05"),
    ({"po_matched": False, "amount": 900}, "needs_approval", "AP-06"),
    ({"amount": 48500}, "needs_approval", "AP-07"),
    ({"amount": 900}, "auto_pay", "AP-08"),
]


@pytest.mark.skipif(not LIVE, reason="set K9_TEST_GORULES_URL to run against a GoRules agent")
@pytest.mark.parametrize("change,decision,rule", CASES)
def test_live_accounts_payable_rules(change, decision, rule):
    facts = {**INVOICE, **change}
    out = GoRulesAdapter({**CFG, "engine_url": LIVE, "facts": None}).execute(facts)
    assert out["status"] == "success", out
    assert (out["decision"]["decision"], out["decision"]["rule"]) == (decision, rule), out["decision"]
