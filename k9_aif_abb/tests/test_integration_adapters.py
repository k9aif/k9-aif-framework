# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tests for integration adapter ABBs.

All tests are fully offline — no HTTP, no Kafka, no DB, no LLM.
Concrete subclasses are defined inline per test to verify the ABB contracts.
"""

import pytest
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_adapters.integration import (
    BaseIntegrationAdapter,
    BaseApiAdapter,
    BaseMessagingAdapter,
    BaseRulesAdapter,
    BaseWorkflowAdapter,
    BaseProcessFlowAdapter,
    BaseBpmAdapter,
    BaseDataAdapter,
    IntegrationAdapterFactory,
)


# ── Minimal concrete implementations for testing ──────────────────────────────

class _StubApiAdapter(BaseApiAdapter):
    def call_endpoint(self, url, method, headers, body):
        return {"url": url, "method": method, "echo": body}


class _FailingApiAdapter(BaseApiAdapter):
    def call_endpoint(self, url, method, headers, body):
        raise ConnectionError("endpoint unreachable")


class _ValidatingApiAdapter(BaseApiAdapter):
    def validate_input(self, payload):
        if "url" not in payload and "url" not in self.config:
            raise ValueError("url is required")

    def call_endpoint(self, url, method, headers, body):
        return {"ok": True}


class _StubMessagingAdapter(BaseMessagingAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.published = []

    def publish(self, topic, message):
        self.published.append((topic, message))
        return {"offset": len(self.published)}


class _StubRulesAdapter(BaseRulesAdapter):
    def evaluate(self, ruleset, facts):
        return {"approved": facts.get("amount", 0) < 10000, "ruleset": ruleset}


class _StubWorkflowAdapter(BaseWorkflowAdapter):
    def trigger(self, workflow_id, params):
        return {"run_id": f"run-{workflow_id}-001", "state": "running"}


class _StubProcessFlowAdapter(BaseProcessFlowAdapter):
    def invoke(self, flow_id, payload):
        return {"flow_id": flow_id, "status": "triggered"}


class _StubBpmAdapter(BaseBpmAdapter):
    def start_process(self, process_key, variables):
        return {"instance_id": f"inst-{process_key}-001"}


class _StubDataAdapter(BaseDataAdapter):
    _ROWS = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def read(self, query, params=None):
        return self._ROWS

    def write(self, data, target=None):
        return {"rows_written": 1}


# ── BaseIntegrationAdapter ────────────────────────────────────────────────────

def test_cannot_instantiate_base_directly():
    with pytest.raises(TypeError):
        BaseIntegrationAdapter()


def test_adapter_name_defaults_to_class_name():
    a = _StubApiAdapter()
    assert a.adapter_name == "_StubApiAdapter"


def test_config_defaults_to_empty_dict():
    a = _StubApiAdapter()
    assert a.config == {}


def test_config_is_stored():
    a = _StubApiAdapter(config={"url": "http://example.com"})
    assert a.config["url"] == "http://example.com"


def test_handle_error_returns_structured_dict():
    a = _StubApiAdapter()
    result = a.handle_error(ValueError("bad input"), {"x": 1})
    assert result["status"] == "error"
    assert result["adapter"] == "_StubApiAdapter"
    assert "bad input" in result["error"]
    assert result["error_type"] == "ValueError"


def test_validate_input_is_noop_by_default():
    a = _StubApiAdapter()
    a.validate_input({"anything": True})   # must not raise


# ── BaseApiAdapter ────────────────────────────────────────────────────────────

def test_api_execute_success():
    a = _StubApiAdapter(config={"url": "http://api.example.com", "method": "POST"})
    result = a.execute({"claim_id": "C001"})
    assert result["status"] == "success"
    assert result["result"]["url"] == "http://api.example.com"
    assert result["result"]["method"] == "POST"


def test_api_execute_url_from_payload():
    a = _StubApiAdapter()
    result = a.execute({"url": "http://dynamic.example.com"})
    assert result["status"] == "success"
    assert result["result"]["url"] == "http://dynamic.example.com"


def test_api_execute_merges_headers():
    a = _StubApiAdapter(config={"url": "http://api.example.com", "headers": {"X-App": "k9x"}})
    result = a.execute({"headers": {"X-Req": "123"}})
    assert result["status"] == "success"


def test_api_execute_handles_exception():
    a = _FailingApiAdapter(config={"url": "http://api.example.com"})
    result = a.execute({})
    assert result["status"] == "error"
    assert "endpoint unreachable" in result["error"]


def test_api_validate_input_raises_on_missing_url():
    a = _ValidatingApiAdapter()
    with pytest.raises(ValueError, match="url is required"):
        a.execute({"data": "x"})


def test_api_validate_passes_when_url_in_config():
    a = _ValidatingApiAdapter(config={"url": "http://ok.example.com"})
    result = a.execute({"data": "x"})
    assert result["status"] == "success"


# ── BaseMessagingAdapter ──────────────────────────────────────────────────────

def test_messaging_publish_mode():
    a = _StubMessagingAdapter(config={"topic": "claims.events", "mode": "publish"})
    result = a.execute({"event_type": "claim_submitted"})
    assert result["status"] == "success"
    assert result["mode"] == "publish"
    assert len(a.published) == 1
    assert a.published[0][0] == "claims.events"


def test_messaging_topic_from_payload():
    a = _StubMessagingAdapter()
    result = a.execute({"topic": "payments.out", "amount": 500})
    assert result["status"] == "success"
    assert a.published[0][0] == "payments.out"


def test_messaging_consume_raises_not_implemented_by_default():
    a = _StubMessagingAdapter(config={"topic": "t", "mode": "consume"})
    result = a.execute({})
    assert result["status"] == "error"
    assert "consume" in result["error"]


def test_messaging_publish_multiple_events():
    a = _StubMessagingAdapter(config={"topic": "events"})
    a.execute({"id": 1})
    a.execute({"id": 2})
    assert len(a.published) == 2


# ── BaseRulesAdapter ──────────────────────────────────────────────────────────

def test_rules_evaluate_approval():
    a = _StubRulesAdapter(config={"ruleset": "claims-policy-v2"})
    result = a.execute({"amount": 500})
    assert result["status"] == "success"
    assert result["decision"]["approved"] is True
    assert result["ruleset"] == "claims-policy-v2"


def test_rules_evaluate_rejection():
    a = _StubRulesAdapter(config={"ruleset": "claims-policy-v2"})
    result = a.execute({"amount": 99999})
    assert result["decision"]["approved"] is False


def test_rules_ruleset_from_payload():
    a = _StubRulesAdapter()
    result = a.execute({"ruleset": "fraud-rules-v1", "amount": 100})
    assert result["ruleset"] == "fraud-rules-v1"


# ── BaseWorkflowAdapter ───────────────────────────────────────────────────────

def test_workflow_trigger_success():
    a = _StubWorkflowAdapter(config={"workflow_id": "claims-approval-dag"})
    result = a.execute({"claim_id": "C001"})
    assert result["status"] == "success"
    assert result["workflow_id"] == "claims-approval-dag"
    assert "run" in result
    assert "run-claims-approval-dag" in result["run"]["run_id"]


def test_workflow_id_from_payload():
    a = _StubWorkflowAdapter()
    result = a.execute({"workflow_id": "payment-dag", "amount": 100})
    assert result["workflow_id"] == "payment-dag"


def test_workflow_get_status_returns_none_by_default():
    a = _StubWorkflowAdapter()
    assert a.get_status("run-001") is None


# ── BaseProcessFlowAdapter ────────────────────────────────────────────────────

def test_process_flow_invoke_success():
    a = _StubProcessFlowAdapter(config={"flow_id": "mulesoft-claims-flow"})
    result = a.execute({"claim_id": "C001"})
    assert result["status"] == "success"
    assert result["flow_id"] == "mulesoft-claims-flow"
    assert result["result"]["status"] == "triggered"


def test_process_flow_id_from_payload():
    a = _StubProcessFlowAdapter()
    result = a.execute({"flow_id": "tibco-payments", "ref": "P001"})
    assert result["flow_id"] == "tibco-payments"


# ── BaseBpmAdapter ────────────────────────────────────────────────────────────

def test_bpm_start_process_success():
    a = _StubBpmAdapter(config={"process_definition_key": "claims-adjudication"})
    result = a.execute({"claim_id": "C001"})
    assert result["status"] == "success"
    assert result["process_key"] == "claims-adjudication"
    assert "inst-claims-adjudication" in result["instance"]["instance_id"]


def test_bpm_get_task_returns_none_by_default():
    a = _StubBpmAdapter()
    assert a.get_task("inst-001") is None


# ── BaseDataAdapter ───────────────────────────────────────────────────────────

def test_data_read_success():
    a = _StubDataAdapter(config={"operation": "read"})
    result = a.execute({"query": "SELECT * FROM claims"})
    assert result["status"] == "success"
    assert result["operation"] == "read"
    assert result["count"] == 2
    assert result["rows"][0]["name"] == "Alice"


def test_data_write_success():
    a = _StubDataAdapter(config={"operation": "write"})
    result = a.execute({"name": "Carol", "amount": 500})
    assert result["status"] == "success"
    assert result["operation"] == "write"
    assert result["result"]["rows_written"] == 1


def test_data_default_operation_is_read():
    a = _StubDataAdapter()
    result = a.execute({"query": "SELECT 1"})
    assert result["operation"] == "read"


def test_data_write_raises_not_implemented_on_base():
    class _ReadOnlyData(BaseDataAdapter):
        def read(self, query, params=None):
            return []
    a = _ReadOnlyData(config={"operation": "write"})
    result = a.execute({})
    assert result["status"] == "error"
    assert "write" in result["error"]


# ── IntegrationAdapterFactory ─────────────────────────────────────────────────

def test_factory_register_and_get():
    IntegrationAdapterFactory.register("test_api", _StubApiAdapter)
    adapter = IntegrationAdapterFactory.get("test_api", config={"url": "http://x.com"})
    assert isinstance(adapter, _StubApiAdapter)
    assert adapter.config["url"] == "http://x.com"


def test_factory_create_alias():
    IntegrationAdapterFactory.register("test_rules", _StubRulesAdapter)
    adapter = IntegrationAdapterFactory.create("test_rules")
    assert isinstance(adapter, _StubRulesAdapter)


def test_factory_unknown_raises_value_error():
    with pytest.raises(ValueError, match="No adapter registered"):
        IntegrationAdapterFactory.get("nonexistent_xyz")


def test_factory_registered_returns_list():
    IntegrationAdapterFactory.register("test_msg", _StubMessagingAdapter)
    assert "test_msg" in IntegrationAdapterFactory.registered()


def test_factory_cannot_instantiate():
    with pytest.raises(RuntimeError):
        IntegrationAdapterFactory()
