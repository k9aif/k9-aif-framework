# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.30.0 -- HIL requests conform to K9X HIL's task contract (k9x.hil.task/v1).

Property: every message BaseHILOrchestrator publishes validates against the schema K9X HIL publishes and enforces
(HIL dead-letters anything else), and a value HIL would refuse fails where it is set, at the RequiresHIL raise site,
before the flow pauses. The fixture is a copy of k9x-hil's contract/k9x.hil.task.v1.schema.json; HIL owns it.
"""

import json
from pathlib import Path

import pytest

from k9_aif_abb.k9_core.orchestration.base_hil_orchestrator import BaseHILOrchestrator
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_core.orchestration.hil_task import HILArtifact, build_hil_task_message

jsonschema = pytest.importorskip("jsonschema")

FIXTURE = Path(__file__).parent / "fixtures" / "k9x.hil.task.v1.schema.json"
SCHEMA = json.loads(FIXTURE.read_text())
HIL_REPO_SCHEMA = Path(__file__).resolve().parents[3] / "k9x-hil" / "contract" / "k9x.hil.task.v1.schema.json"


def _errors(message):
    return [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(message)]


class _Bus:
    def __init__(self):
        self.sent = []

    def publish_to(self, topic, message):
        self.sent.append((topic, message))

    def publish(self, message):
        pass


class _Orch(BaseOrchestrator):
    layer = "APOrchestrator"

    def execute_flow(self, payload):
        raise NotImplementedError


def _publish(exc: RequiresHIL):
    bus = _Bus()
    hil = BaseHILOrchestrator(config={}, message_bus=bus, state_store=None)
    orch = _Orch(config={}, message_bus=bus)
    orch._get_hil_orchestrator = lambda: hil
    out = orch.handle_requires_hil(exc, {"event_type": "openai.ap.invoice", "prompt": "x"})
    requests = [(t, m) for t, m in bus.sent if t.startswith("hil.requests.")]
    assert out["status"] == "pending_hil" and len(requests) == 1
    return requests[0]


def test_fixture_matches_the_hil_repository_copy():
    if not HIL_REPO_SCHEMA.exists():
        pytest.skip("k9x-hil checkout not next to the framework")
    assert json.loads(HIL_REPO_SCHEMA.read_text()) == SCHEMA


def test_a_plain_requires_hil_publishes_a_conforming_task():
    topic, msg = _publish(RequiresHIL("rules engine unavailable", context={"adapter": "gorules"}, queue="ap"))
    assert topic == "hil.requests.ap" and msg["contract"] == "k9x.hil.task/v1"
    assert msg["reply_to"] == "hil.replies.ap" and msg["source_topic"] == "hil.requests.ap"
    assert _errors(msg) == []


def test_every_task_field_reaches_hil_and_conforms():
    exc = RequiresHIL(
        "Invoice over $15,000 (AP-07)", context={"vendor": "Acme Supplies", "amount": 48500}, priority="high",
        queue="openai-ap-payments", title="Approve payment of INV-1042", task_type="invoice-approval",
        required_role="manager", decision_authority="Accounts payable manager", require_comment=True,
        ttl_hours=24, ttl_action="reject", pii=True, pii_fields=["bank_account"],
        artifacts=[HILArtifact("s3://openai-ap-invoices/INV-1042.pdf", "Invoice INV-1042", "application/pdf", "primary"),
                   {"uri": "https://openai.k9x.ai/#ap", "title": "The run", "role": "supporting"},
                   "s3://openai-ap-invoices/INV-1042-po.pdf"])
    _, msg = _publish(exc)
    assert _errors(msg) == []
    assert (msg["title"], msg["description"], msg["task_type"], msg["required_role"]) == \
        ("Approve payment of INV-1042", "Invoice over $15,000 (AP-07)", "invoice-approval", "manager")
    assert [a["uri"] for a in msg["artifacts"]] == ["s3://openai-ap-invoices/INV-1042.pdf", "https://openai.k9x.ai/#ap",
                                                     "s3://openai-ap-invoices/INV-1042-po.pdf"]
    assert msg["payload"] == {"vendor": "Acme Supplies", "amount": 48500}


def test_the_orchestrator_can_fill_in_fields_after_catching_the_signal():
    exc = RequiresHIL("PaymentAgent wants to run pay_invoice", queue="openai-ap-payments")
    exc.set_task_fields(task_type="invoice-approval", required_role="manager",
                        artifacts=["s3://openai-ap-invoices/INV-2001.pdf"])
    _, msg = _publish(exc)
    assert _errors(msg) == [] and msg["required_role"] == "manager" and len(msg["artifacts"]) == 1


@pytest.mark.parametrize("kwargs", [
    {"priority": "urgent"}, {"required_role": "boss"}, {"ttl_action": "approve"}, {"ttl_hours": 0},
    {"task_type": "Invoice Approval"}, {"artifacts": ["ftp://x/y"]}, {"artifacts": [{"uri": "s3://b/k", "x": 1}]},
    {"artifacts": [{"uri": "s3://b/k", "role": "main"}]},
])
def test_a_value_hil_would_refuse_fails_at_the_raise_site(kwargs):
    with pytest.raises(ValueError):
        RequiresHIL("x", **kwargs)


def test_set_task_fields_is_checked_too():
    with pytest.raises(ValueError):
        RequiresHIL("x").set_task_fields(required_role="boss")
    with pytest.raises(ValueError):
        RequiresHIL("x").set_task_fields(colour="red")


def test_the_builder_omits_unset_optional_fields():
    msg = build_hil_task_message(correlation_id="c", reply_to="hil.replies.q", title="t")
    assert _errors(msg) == [] and "task_type" not in msg and "required_role" not in msg
