# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — Web UI and Architecture Demo API tests

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─── Conftest adds repo root to sys.path ──────────────────────────────────────

WEBUI_DIR = Path(__file__).resolve().parents[1] / "webui"
EOC_ROOT  = Path(__file__).resolve().parents[1]


# ─── WebUI file existence ──────────────────────────────────────────────────────

class TestWebUIFiles:
    def test_webui_directory_exists(self):
        assert WEBUI_DIR.is_dir(), "webui/ directory must exist"

    def test_index_html_exists(self):
        assert (WEBUI_DIR / "index.html").is_file()

    def test_app_js_exists(self):
        assert (WEBUI_DIR / "app.js").is_file()

    def test_styles_css_exists(self):
        assert (WEBUI_DIR / "styles.css").is_file()

    def test_index_html_has_required_elements(self):
        content = (WEBUI_DIR / "index.html").read_text()
        assert "K9-AIF Enterprise Insurance Operations Center" in content
        assert "pipeline-flow" in content
        assert "scenario-list" in content
        assert "trace-console" in content
        assert "app.js" in content
        assert "styles.css" in content

    def test_app_js_has_required_functions(self):
        content = (WEBUI_DIR / "app.js").read_text()
        assert "runScenario" in content
        assert "selectScenario" in content
        assert "animatePipeline" in content
        assert "renderTab" in content
        assert "connectSSE" in content


# ─── Scenarios endpoint ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient with mocked LLM/orchestrator to avoid real I/O."""
    with patch("k9_aif_abb.k9_factories.model_router_factory.ModelRouterFactory.get_router",
               return_value=MagicMock()), \
         patch("k9_aif_abb.k9_factories.llm_factory.LLMFactory.bootstrap"), \
         patch("k9_aif_abb.k9_factories.llm_factory.LLMFactory.is_bootstrapped", return_value=False):
        from examples.K9X_Enterprise_Insurance_OperationsCenter.api.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestScenariosEndpoint:
    def test_scenarios_returns_200(self, client):
        r = client.get("/api/eoc/scenarios")
        assert r.status_code == 200

    def test_scenarios_has_all_seven(self, client):
        data = client.get("/api/eoc/scenarios").json()
        ids = {s["id"] for s in data["scenarios"]}
        expected = {
            "claim_submitted", "document_received", "fraud_signal_raised",
            "policy_change_requested", "catastrophe_alert_issued",
            "customer_interaction_logged", "audit_query_received",
        }
        assert ids == expected

    def test_scenario_has_required_fields(self, client):
        data = client.get("/api/eoc/scenarios").json()
        for s in data["scenarios"]:
            assert "id" in s
            assert "label" in s
            assert "squad" in s
            assert "agents" in s
            assert "sample_payload" in s
            assert "description" in s

    def test_scenario_claim_has_sample_payload(self, client):
        data = client.get("/api/eoc/scenarios").json()
        claim = next(s for s in data["scenarios"] if s["id"] == "claim_submitted")
        payload = claim["sample_payload"]
        assert "claimant_id" in payload
        assert "amount_claimed" in payload


# ─── Architecture endpoint ─────────────────────────────────────────────────────

class TestArchitectureEndpoint:
    def test_architecture_returns_200(self, client):
        r = client.get("/api/eoc/architecture")
        assert r.status_code == 200

    def test_architecture_has_top_level_keys(self, client):
        data = client.get("/api/eoc/architecture").json()
        for key in ("router", "orchestrator", "squads", "agents", "governance", "model_routing"):
            assert key in data, f"Missing key: {key}"

    def test_architecture_router_has_routing_table(self, client):
        data = client.get("/api/eoc/architecture").json()
        rt = data["router"]["routing_table"]
        assert "claim_submitted" in rt
        assert "fraud_signal_raised" in rt

    def test_architecture_has_seven_squads(self, client):
        data = client.get("/api/eoc/architecture").json()
        assert len(data["squads"]) == 7

    def test_architecture_agents_include_guard(self, client):
        data = client.get("/api/eoc/architecture").json()
        classes = [a["class"] for a in data["agents"]]
        assert "GuardAgent" in classes
        assert "AuditAgent" in classes

    def test_governance_has_required_policies(self, client):
        data = client.get("/api/eoc/architecture").json()
        gov = data["governance"]
        assert "pii_guard" in gov
        assert "confidence_threshold" in gov
        assert "audit_all_actions" in gov


# ─── Config summary endpoint ───────────────────────────────────────────────────

class TestConfigSummaryEndpoint:
    def test_config_summary_returns_200(self, client):
        r = client.get("/api/eoc/config-summary")
        assert r.status_code == 200

    def test_config_summary_has_sections(self, client):
        data = client.get("/api/eoc/config-summary").json()
        for key in ("inference", "messaging", "governance", "eoc"):
            assert key in data


# ─── Run scenario endpoint ─────────────────────────────────────────────────────

class TestRunScenarioEndpoint:
    def test_run_unknown_event_type_returns_422(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "not_a_real_event"})
        assert r.status_code == 422

    def test_run_returns_trace_list(self, client):
        """Even in stub/error mode, a trace list must be returned."""
        r = client.post("/api/eoc/run", json={
            "event_type": "claim_submitted",
            "payload": {
                "claimant_id": "CLM-TEST-01",
                "policy_id": "POL-TEST-99",
                "claim_type": "property_damage",
                "amount_claimed": 1000,
            }
        })
        assert r.status_code == 200
        data = r.json()
        assert "trace" in data
        assert isinstance(data["trace"], list)
        assert len(data["trace"]) > 0

    def test_run_returns_event_id_and_correlation(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "audit_query_received"})
        assert r.status_code == 200
        data = r.json()
        assert "event_id" in data
        assert "correlation_id" in data

    def test_run_trace_steps_have_required_fields(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "fraud_signal_raised"})
        data = r.json()
        for step in data["trace"]:
            assert "step" in step
            assert "component" in step
            assert "layer" in step
            assert "status" in step
            assert "message" in step

    def test_run_first_trace_step_is_router(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "claim_submitted"})
        data = r.json()
        first = data["trace"][0]
        assert first["component"] == "EOCRouter"
        assert first["layer"] == "router"

    def test_run_uses_default_sample_payload_when_none_given(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "document_received"})
        assert r.status_code == 200

    def test_run_final_trace_step_is_pipeline(self, client):
        r = client.post("/api/eoc/run", json={"event_type": "policy_change_requested"})
        data = r.json()
        last = data["trace"][-1]
        assert last.get("final") is True


# ─── Static files + root redirect ─────────────────────────────────────────────

class TestStaticServing:
    def test_root_redirects_to_webui(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308)
        assert "webui" in r.headers.get("location", "")

    def test_webui_index_served(self, client):
        r = client.get("/webui/index.html")
        assert r.status_code == 200
        assert "K9-AIF" in r.text

    def test_webui_styles_served(self, client):
        r = client.get("/webui/styles.css")
        assert r.status_code == 200

    def test_webui_app_js_served(self, client):
        r = client.get("/webui/app.js")
        assert r.status_code == 200
