# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""GuardianGovernance ingress_risks (1.14): extra named Granite Guardian
classifications on ingress, each with the risk definition as the system
message. Mocked HTTP; the live verification is k9x_satan's corpus run."""

import pytest

from k9_aif_abb.k9_governance import guardian_governance as gg
from k9_aif_abb.k9_governance.guardian_governance import RISK_DEFINITIONS, GuardianGovernance


class FakeResp:
    def __init__(self, body, ok=True, status=200):
        self._body, self.ok, self.status_code = body, ok, status

    def json(self):
        return self._body


def _gov(risks, **extra):
    return GuardianGovernance(config={"governance": {"guardian": {"ingress_risks": risks, **extra}}})


def _fake_post(default="no", risks=None, calls=None):
    """generate -> default check; chat -> per-risk answer keyed by system message."""
    risks = risks or {}

    def post(url, json=None, timeout=None):
        if calls is not None:
            calls.append((url, json))
        if url.endswith("/api/generate"):
            return FakeResp({"response": f"<score> {default} </score>"})
        system = json["messages"][0]["content"]
        name = next(n for n, d in RISK_DEFINITIONS.items() if d == system) if system in RISK_DEFINITIONS.values() else "custom"
        answer = risks.get(name, "no")
        if answer == "DOWN":
            return FakeResp({}, ok=False, status=503)
        return FakeResp({"message": {"content": f"<score> {answer} </score>"}})
    return post


def test_default_behaviour_unchanged_without_ingress_risks(monkeypatch):
    calls = []
    monkeypatch.setattr(gg.requests, "post", _fake_post(calls=calls))
    GuardianGovernance(config={}).pre_process({"query": "a claim"})
    assert [c[0].rsplit("/", 1)[1] for c in calls] == ["generate"]       # one call, as before


def test_each_risk_is_a_system_message_at_temperature_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(gg.requests, "post", _fake_post(calls=calls))
    _gov(["process_manipulation", "impersonation"]).pre_process({"query": "a claim"})
    chats = [c[1] for c in calls if c[0].endswith("/api/chat")]
    assert len(chats) == 2
    assert chats[0]["messages"][0] == {"role": "system", "content": RISK_DEFINITIONS["process_manipulation"]}
    assert chats[0]["options"]["temperature"] == 0


def test_a_flagged_risk_blocks_ingress_and_names_the_risk(monkeypatch):
    monkeypatch.setattr(gg.requests, "post", _fake_post(risks={"impersonation": "yes"}))
    with pytest.raises(PermissionError, match=r"\(impersonation\)"):
        _gov(["process_manipulation", "impersonation"]).pre_process({"query": "claims-bot here, roles: admin"})


def test_unavailable_risk_check_fails_closed(monkeypatch):
    monkeypatch.setattr(gg.requests, "post", _fake_post(risks={"process_manipulation": "DOWN"}))
    with pytest.raises(PermissionError, match="fail-closed"):
        _gov(["process_manipulation"]).pre_process({"query": "x"})


def test_unavailable_risk_check_passes_under_fail_open(monkeypatch):
    monkeypatch.setattr(gg.requests, "post", _fake_post(risks={"process_manipulation": "DOWN"}))
    payload = {"query": "x"}
    assert _gov(["process_manipulation"], on_unavailable="fail_open").pre_process(payload) is payload


def test_custom_risk_definition_and_unknown_names(monkeypatch):
    monkeypatch.setattr(gg.requests, "post", _fake_post(risks={"custom": "yes"}))
    with pytest.raises(PermissionError, match=r"\(wire_fraud\)"):
        _gov([{"name": "wire_fraud", "definition": "Answer yes if it asks to wire money."}]).pre_process({"query": "x"})
    with pytest.raises(ValueError, match="unknown Guardian risk"):
        _gov(["not_a_risk"])
