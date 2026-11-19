# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""ACME flows through the squad layer: orchestrators load squads by id, the squads run the agents.

Model calls are stubbed and the claim store is not touched; everything else is the real
code path (SquadLoader.from_agents → AcmeOrchestrator → domain orchestrator → BaseSquad →
sync and async agents). Run from the framework root:

    K9_ENV=test pytest examples/acme_health_insurance/tests/test_squad_flows.py
"""

import asyncio
import copy
import os
import types
from pathlib import Path

import pytest

os.environ.setdefault("K9_ENV", "test")

from k9_aif_abb.k9_squad.squad_loader import SquadLoader  # noqa: E402
from k9_aif_abb.k9_utils.config_loader import load_yaml  # noqa: E402

APP = Path(__file__).resolve().parent.parent


def _reply(text):
    return types.SimpleNamespace(output=text, model_alias="general", provider="stub")


@pytest.fixture
def app(monkeypatch, tmp_path):
    import examples.acme_health_insurance.agents.claim_processing_agent as cpa
    import examples.acme_health_insurance.agents.persistence_agent as pa
    import examples.acme_health_insurance.agents.retriever_agent as ra
    import examples.acme_health_insurance.orchestrators.claims_orchestrator as co
    from examples.acme_health_insurance.orchestrators.acme_orchestrator import AcmeOrchestrator
    from examples.acme_health_insurance.orchestrators.user_orchestrator import UserOrchestrator

    calls = {"model": [], "fail": None}

    def fake_llm(config, req):
        stage = (req.metadata or {}).get("stage") or (req.metadata or {}).get("mode")
        calls["model"].append(stage)
        if calls["fail"] == stage:
            raise RuntimeError(f"model unreachable ({stage})")
        return _reply({"intent_classification": "submit_claim", "compliance": "no issues"}.get(stage, "a summary"))

    for mod in (cpa, ra, co):
        monkeypatch.setattr(mod, "llm_invoke", fake_llm)
    monkeypatch.setattr(pa.PersistenceAgent, "execute", lambda self, p: {"status": "success", "row_id": 1})

    config = copy.deepcopy(load_yaml(str(APP / "config" / "config.yaml")))
    config["governance"]["guardian"]["enabled"] = False      # no Guardian model in unit tests
    config["persistence"] = {"db_path": str(tmp_path / "claims.db")}   # same shape as config.yaml
    squads = SquadLoader.from_agents(APP / "agents" / "yaml", config=config)
    return types.SimpleNamespace(
        acme=AcmeOrchestrator(config=config, squads=squads),
        user=UserOrchestrator(config=config, squads=squads),
        calls=calls)


def test_sign_in_runs_the_auth_squad(app):
    out = asyncio.run(app.user.execute_flow({"action": "signin", "username": "pat"}))
    assert out["status"] == "signed_in" and "pat" in out["reply"]


def test_claim_runs_the_claims_squad_with_its_async_agent(app):
    out = asyncio.run(app.acme.execute_flow({"intent": "claims_support", "message": "I want to file a claim"}))
    assert "Claim filed successfully" in out["reply"], out
    assert app.calls["model"] == ["intent_classification", "reasoning", "compliance"]


def test_failed_compliance_check_is_an_error_not_clear(app):
    app.calls["fail"] = "compliance"
    out = asyncio.run(app.acme.execute_flow({"intent": "claims_support", "message": "file a claim"}))
    assert out.get("status") == "error" and "compliance" in out["reply"]
    assert "Claim filed" not in out["reply"]


def test_plan_question_runs_the_plan_lookup_squad(app):
    out = asyncio.run(app.acme.execute_flow({"intent": "health_plan", "message": "What does GoldCare cover?"}))
    assert out["reply"].startswith("**ACME HealthCare Plan Information:**"), out
    assert "a summary" in out["reply"]


def test_fallback_and_live_agent_orchestrators_resolve(app):
    for intent in ("fallback", "talk_to_agent"):
        out = asyncio.run(app.acme.execute_flow({"intent": intent, "message": "hello"}))
        assert out.get("status") != "error", (intent, out)
