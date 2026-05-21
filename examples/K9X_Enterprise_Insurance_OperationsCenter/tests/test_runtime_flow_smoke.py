# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — test_runtime_flow_smoke.py
#
# Smoke test for the full runtime flow:
#   payload → EOCRouter → (mocked Kafka) → orchestrator creation
#   → OrchestratorLoader → SquadLoader → squad execution → mocked agents → result
#
# No real Kafka. No real LLMs. All agents are mocked.

from unittest.mock import MagicMock, patch, call
from pathlib import Path
import pytest

EOC_ROOT     = Path(__file__).resolve().parents[1]
SQUADS_YAML  = str(EOC_ROOT / "config" / "squads.yaml")

from k9_aif_abb.k9_orchestrators.orchestrator_loader import OrchestratorLoader
from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_orchestrators.registry.orchestrator_registry import OrchestratorRegistry

from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router import EOCRouter, _ROUTING_TABLE
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.claims_processing_orchestrator import ClaimsProcessingOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_agent(name: str, return_value: dict) -> MagicMock:
    agent = MagicMock()
    agent.__class__ = type(name, (), {})
    agent.__class__.__name__ = name
    agent.execute = MagicMock(return_value=return_value)
    return agent


# ---------------------------------------------------------------------------
# Test 1: EOCRouter → correct Kafka topic
# ---------------------------------------------------------------------------

def test_router_routes_claim_to_correct_topic():
    with patch("examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus") as MockBus:
        mock_bus_instance = MagicMock()
        MockBus.return_value = mock_bus_instance

        router = EOCRouter(config={"messaging": {"brokers": ["localhost:9092"]}})
        payload = {"event_id": "E001", "correlation_id": "C001", "claim_id": "CLM-001"}

        result = router.route("claim_submitted", payload)

    assert result is True
    mock_bus_instance.publish.assert_called_once()
    published_payload = mock_bus_instance.publish.call_args[0][0]
    assert published_payload["event_type"] == "claim_submitted"
    assert published_payload["event_id"] == "E001"


def test_router_does_not_instantiate_orchestrator():
    with patch("examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus"):
        router = EOCRouter(config={})

    # router has no _squad, no _agent_map — purely routing
    assert not hasattr(router, "_squad")
    assert not hasattr(router, "_agent_map")
    assert not hasattr(router, "handle_event")


# ---------------------------------------------------------------------------
# Test 2: OrchestratorLoader creates ClaimsProcessingOrchestrator
# ---------------------------------------------------------------------------

def test_orchestrator_loader_creates_claims_orchestrator():
    loader = OrchestratorLoader(registry={"claims": ClaimsProcessingOrchestrator})
    instance = loader.load({"type": "claims", "id": "claims_orch"})
    assert isinstance(instance, ClaimsProcessingOrchestrator)
    assert instance._squad is None   # not started yet — no SquadLoader called


# ---------------------------------------------------------------------------
# Test 3: SquadLoader loads ClaimsProcessingSquad from squads.yaml
# ---------------------------------------------------------------------------

def test_squad_loader_loads_claims_squad():
    # SquadLoader.load_one() calls load() internally which processes ALL squads.
    # All agent types referenced anywhere in squads.yaml must be registered.
    stub = lambda name: make_mock_agent(name, {"status": "ok"})

    agent_registry = AgentRegistry()
    for name in [
        "ClaimsTriageAgent", "AdjudicationAgent", "GuardAgent",
        "AuditAgent", "EscalationAgent", "DocumentExtractorAgent",
        "FraudDetectionAgent", "GraphSyncAgent",
    ]:
        n = name  # capture loop variable
        agent_registry.register(n, lambda _n=n: stub(_n))

    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.document_intelligence_orchestrator import DocumentIntelligenceOrchestrator
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.risk_assessment_orchestrator import RiskAssessmentOrchestrator
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.policy_management_orchestrator import PolicyManagementOrchestrator
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.catastrophe_response_orchestrator import CatastropheResponseOrchestrator
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.customer_service_orchestrator import CustomerServiceOrchestrator
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.audit_compliance_orchestrator import AuditComplianceOrchestrator

    orchestrator_registry = OrchestratorRegistry()
    orchestrator_registry.register("ClaimsProcessingOrchestrator",    ClaimsProcessingOrchestrator)
    orchestrator_registry.register("DocumentIntelligenceOrchestrator", DocumentIntelligenceOrchestrator)
    orchestrator_registry.register("RiskAssessmentOrchestrator",      RiskAssessmentOrchestrator)
    orchestrator_registry.register("PolicyManagementOrchestrator",    PolicyManagementOrchestrator)
    orchestrator_registry.register("CatastropheResponseOrchestrator", CatastropheResponseOrchestrator)
    orchestrator_registry.register("CustomerServiceOrchestrator",     CustomerServiceOrchestrator)
    orchestrator_registry.register("AuditComplianceOrchestrator",     AuditComplianceOrchestrator)

    loader = SquadLoader(agent_registry, orchestrator_registry)
    squad  = loader.load_one(SQUADS_YAML, "ClaimsProcessingSquad")

    assert squad is not None
    agent_names = {a.__class__.__name__ for a in squad.agents}
    assert "ClaimsTriageAgent" in agent_names
    assert "AdjudicationAgent" in agent_names
    assert "GuardAgent"        in agent_names
    assert "AuditAgent"        in agent_names
    assert "EscalationAgent"   in agent_names


# ---------------------------------------------------------------------------
# Test 4: Full flow — orchestrator.execute_flow() executes agents sequentially
# ---------------------------------------------------------------------------

def test_claims_orchestrator_execute_flow_executes_agents_in_order():
    call_order = []

    def triage_fn(payload):
        call_order.append("ClaimsTriageAgent")
        return {"priority": "high", "confidence": 0.92, "completeness_score": 1.0}

    def adjudication_fn(payload):
        call_order.append("AdjudicationAgent")
        assert "triage" in payload   # triage result must be in context
        return {"decision": "approve", "confidence": 0.88, "rationale": "Looks valid"}

    def guard_fn(payload):
        call_order.append("GuardAgent")
        assert "adjudication" in payload
        return {"passed": True, "pii_detected": False}

    def audit_fn(payload):
        call_order.append("AuditAgent")
        return {"audit_id": "AUD-TEST", "status": "written"}

    def escalation_fn(payload):
        call_order.append("EscalationAgent")
        return {"escalated": False}

    mock_triage     = MagicMock(); mock_triage.__class__.__name__ = "ClaimsTriageAgent";  mock_triage.execute = triage_fn
    mock_adjudicate = MagicMock(); mock_adjudicate.__class__.__name__ = "AdjudicationAgent"; mock_adjudicate.execute = adjudication_fn
    mock_guard      = MagicMock(); mock_guard.__class__.__name__ = "GuardAgent";          mock_guard.execute = guard_fn
    mock_audit      = MagicMock(); mock_audit.__class__.__name__ = "AuditAgent";          mock_audit.execute = audit_fn
    mock_escalation = MagicMock(); mock_escalation.__class__.__name__ = "EscalationAgent"; mock_escalation.execute = escalation_fn

    orch = ClaimsProcessingOrchestrator(config={})
    squad = BaseSquad(squad_id="ClaimsProcessingSquad",
                      agents=[mock_triage, mock_adjudicate, mock_guard, mock_audit, mock_escalation],
                      orchestrator=None)
    squad.flow = [
        {"agent": "ClaimsTriageAgent",  "result_key": "triage"},
        {"agent": "AdjudicationAgent",  "result_key": "adjudication"},
        {"agent": "GuardAgent",         "result_key": "guard"},
        {"agent": "AuditAgent",         "result_key": "audit"},
        {"agent": "EscalationAgent",    "result_key": "escalation"},
    ]
    orch._squad = squad

    payload = {
        "event_id":       "E-SMOKE-001",
        "correlation_id": "C-SMOKE-001",
        "claim_id":       "CLM-SMOKE",
        "claimant_id":    "CLMNT-001",
        "policy_id":      "POL-001",
        "claim_type":     "auto",
        "amount_claimed": 5000,
        "notes":          "Smoke test claim",
    }

    result = orch.execute_flow(payload)

    # Verify sequential execution order — all flow agents always run
    assert call_order == [
        "ClaimsTriageAgent",
        "AdjudicationAgent",
        "GuardAgent",
        "AuditAgent",
        "EscalationAgent",
    ], f"Unexpected agent execution order: {call_order}"

    # Result structure
    assert result["status"] == "completed"
    assert result["squad_id"] == "ClaimsProcessingSquad"
    assert result["escalation"] == {"escalated": False}
    assert "triage" in result
    assert "adjudication" in result
    assert "guard" in result
    assert "audit" in result


def test_claims_orchestrator_escalates_on_low_confidence():
    call_order = []

    mock_triage     = MagicMock(); mock_triage.__class__.__name__ = "ClaimsTriageAgent"
    mock_adjudicate = MagicMock(); mock_adjudicate.__class__.__name__ = "AdjudicationAgent"
    mock_guard      = MagicMock(); mock_guard.__class__.__name__ = "GuardAgent"
    mock_audit      = MagicMock(); mock_audit.__class__.__name__ = "AuditAgent"
    mock_escalation = MagicMock(); mock_escalation.__class__.__name__ = "EscalationAgent"

    mock_triage.execute     = lambda p: {"priority": "low", "confidence": 0.5}
    mock_adjudicate.execute = lambda p: {"decision": "review", "confidence": 0.5, "rationale": "Uncertain"}
    mock_guard.execute      = lambda p: {"passed": True, "pii_detected": False}
    mock_audit.execute      = lambda p: {"audit_id": "AUD-ESC", "status": "written"}
    mock_escalation.execute = MagicMock(return_value={"escalated": True, "ticket_id": "ESC-001"})

    orch = ClaimsProcessingOrchestrator(config={})
    squad = BaseSquad(squad_id="ClaimsProcessingSquad",
                      agents=[mock_triage, mock_adjudicate, mock_guard, mock_audit, mock_escalation],
                      orchestrator=None)
    squad.flow = [
        {"agent": "ClaimsTriageAgent",  "result_key": "triage"},
        {"agent": "AdjudicationAgent",  "result_key": "adjudication"},
        {"agent": "GuardAgent",         "result_key": "guard"},
        {"agent": "AuditAgent",         "result_key": "audit"},
        {"agent": "EscalationAgent",    "result_key": "escalation"},
    ]
    orch._squad = squad

    payload = {"event_id": "E-ESC", "correlation_id": "C-ESC", "claim_id": "CLM-ESC",
               "claimant_id": "X", "policy_id": "Y", "claim_type": "health", "amount_claimed": 100}

    result = orch.execute_flow(payload)

    # EscalationAgent is always called in the flow
    mock_escalation.execute.assert_called_once()
    assert result["escalation"] is not None
    assert result["escalation"]["escalated"] is True


# ---------------------------------------------------------------------------
# Test 5: End-to-end — router → loader chain (no Kafka, no LLM)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Test 5a: EOCOrchestrator routes all 7 event_types (E2E routing table)
# ---------------------------------------------------------------------------

def test_eoc_orchestrator_routes_all_event_types():
    """
    E2E: EOCOrchestrator.execute_flow routes all 7 event_types to the correct
    squad handler and returns a well-formed result dict.
    """
    import asyncio
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator import (
        EOCOrchestrator, _ROUTING,
    )

    orch = EOCOrchestrator.__new__(EOCOrchestrator)
    orch.config = {}
    orch._handlers = {}

    for event_type in _ROUTING:
        mock_handler = MagicMock()
        mock_handler.execute_flow.return_value = {
            "status": "completed",
            "squad_id": f"Mock_{event_type}",
        }
        orch._handlers[event_type] = mock_handler

    async def run_all():
        results = {}
        for event_type in _ROUTING:
            payload = {"event_type": event_type, "event_id": "EVT-E2E", "correlation_id": "C-E2E"}
            results[event_type] = await orch.execute_flow(payload)
        return results

    results = asyncio.run(run_all())

    for event_type in _ROUTING:
        assert results[event_type]["status"] == "completed", event_type
        orch._handlers[event_type].execute_flow.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5b: BaseSquad when: condition skips EscalationAgent (high confidence)
# ---------------------------------------------------------------------------

def test_base_squad_when_condition_skips_step_on_false():
    """
    E2E flow with when: — EscalationAgent is NOT called when adjudication
    confidence is high and guard passed.
    """
    mock_triage     = MagicMock(); mock_triage.__class__.__name__ = "ClaimsTriageAgent"
    mock_adjudicate = MagicMock(); mock_adjudicate.__class__.__name__ = "AdjudicationAgent"
    mock_guard      = MagicMock(); mock_guard.__class__.__name__ = "GuardAgent"
    mock_audit      = MagicMock(); mock_audit.__class__.__name__ = "AuditAgent"
    mock_escalation = MagicMock(); mock_escalation.__class__.__name__ = "EscalationAgent"

    mock_triage.execute.return_value     = {"priority": "low", "confidence": 0.9}
    mock_adjudicate.execute.return_value = {"decision": "approve", "confidence": 0.88}
    mock_guard.execute.return_value      = {"passed": True, "pii_detected": False}
    mock_audit.execute.return_value      = {"audit_id": "AUD-WHEN", "status": "written"}

    squad = BaseSquad(
        squad_id="ClaimsProcessingSquad",
        agents=[mock_triage, mock_adjudicate, mock_guard, mock_audit, mock_escalation],
        orchestrator=None,
    )
    squad.flow = [
        {"agent": "ClaimsTriageAgent",  "result_key": "triage"},
        {"agent": "AdjudicationAgent",  "result_key": "adjudication"},
        {"agent": "GuardAgent",         "result_key": "guard"},
        {"agent": "AuditAgent",         "result_key": "audit"},
        {
            "agent": "EscalationAgent",
            "result_key": "escalation",
            "when": {"any": [
                {"key": "adjudication.decision",   "eq":  "escalate"},
                {"key": "adjudication.confidence", "lt":  0.75},
                {"key": "guard.passed",            "eq":  False},
            ]},
        },
    ]

    result = squad.execute({
        "event_id": "E-WHEN", "correlation_id": "C-WHEN",
        "claim_id": "CLM-WHEN", "claimant_id": "X", "policy_id": "Y",
        "claim_type": "auto", "amount_claimed": 1000,
    })

    mock_escalation.execute.assert_not_called()
    assert "escalation" not in result
    assert result["status"] == "completed"


def test_base_squad_when_condition_triggers_step_on_true():
    """
    E2E flow with when: — EscalationAgent IS called when adjudication confidence
    is below the threshold.
    """
    mock_triage     = MagicMock(); mock_triage.__class__.__name__ = "ClaimsTriageAgent"
    mock_adjudicate = MagicMock(); mock_adjudicate.__class__.__name__ = "AdjudicationAgent"
    mock_guard      = MagicMock(); mock_guard.__class__.__name__ = "GuardAgent"
    mock_audit      = MagicMock(); mock_audit.__class__.__name__ = "AuditAgent"
    mock_escalation = MagicMock(); mock_escalation.__class__.__name__ = "EscalationAgent"

    mock_triage.execute.return_value     = {"priority": "high", "confidence": 0.6}
    mock_adjudicate.execute.return_value = {"decision": "review", "confidence": 0.5}
    mock_guard.execute.return_value      = {"passed": True, "pii_detected": False}
    mock_audit.execute.return_value      = {"audit_id": "AUD-ESC2", "status": "written"}
    mock_escalation.execute.return_value = {"escalated": True, "ticket_id": "ESC-WHEN"}

    squad = BaseSquad(
        squad_id="ClaimsProcessingSquad",
        agents=[mock_triage, mock_adjudicate, mock_guard, mock_audit, mock_escalation],
        orchestrator=None,
    )
    squad.flow = [
        {"agent": "ClaimsTriageAgent",  "result_key": "triage"},
        {"agent": "AdjudicationAgent",  "result_key": "adjudication"},
        {"agent": "GuardAgent",         "result_key": "guard"},
        {"agent": "AuditAgent",         "result_key": "audit"},
        {
            "agent": "EscalationAgent",
            "result_key": "escalation",
            "when": {"any": [
                {"key": "adjudication.decision",   "eq":  "escalate"},
                {"key": "adjudication.confidence", "lt":  0.75},
                {"key": "guard.passed",            "eq":  False},
            ]},
        },
    ]

    result = squad.execute({
        "event_id": "E-ESC2", "correlation_id": "C-ESC2",
        "claim_id": "CLM-ESC2", "claimant_id": "X", "policy_id": "Y",
        "claim_type": "health", "amount_claimed": 5000,
    })

    mock_escalation.execute.assert_called_once()
    assert result["escalation"]["escalated"] is True
    assert result["escalation"]["ticket_id"] == "ESC-WHEN"


def test_base_squad_flow_step_missing_agent_field_raises():
    """Flow-step validation: missing 'agent' field raises ValueError at execute time."""
    squad = BaseSquad(squad_id="TestSquad", agents=[], orchestrator=None)
    squad.flow = [{"result_key": "oops"}]  # missing 'agent'
    with pytest.raises(ValueError, match="missing required field 'agent'"):
        squad.execute({"event_id": "X"})


# ---------------------------------------------------------------------------
# Test 5 (original): End-to-end — router → loader chain (no Kafka, no LLM)
# ---------------------------------------------------------------------------

def test_end_to_end_router_to_orchestrator_loader_chain():
    """
    Simulates the full chain:
      router.route() → publish (mocked) → OrchestratorLoader.load() → execute_flow()
    """
    # 1. Router: publishes payload to mock bus
    with patch("examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus") as MockBus:
        mock_bus = MagicMock()
        MockBus.return_value = mock_bus

        router = EOCRouter(config={"messaging": {"brokers": ["localhost:9092"]}})
        payload = {"event_id": "E-E2E", "correlation_id": "C-E2E", "claim_id": "CLM-E2E",
                   "claimant_id": "A", "policy_id": "B", "claim_type": "life", "amount_claimed": 50000}
        routed = router.route("claim_submitted", payload)

    assert routed is True
    published = mock_bus.publish.call_args[0][0]
    assert published["event_type"] == "claim_submitted"

    # 2. OrchestratorLoader: create orchestrator from config
    o_loader = OrchestratorLoader(registry={"claims": ClaimsProcessingOrchestrator})
    orch = o_loader.load({"type": "claims", "id": "claims_orch"})
    assert isinstance(orch, ClaimsProcessingOrchestrator)

    # 3. Wire mocked agents directly (bypasses Kafka/LLM)
    agent_specs = [
        ("ClaimsTriageAgent",  lambda p: {"priority": "critical", "confidence": 0.95}),
        ("AdjudicationAgent",  lambda p: {"decision": "approve", "confidence": 0.9, "rationale": ""}),
        ("GuardAgent",         lambda p: {"passed": True, "pii_detected": False}),
        ("AuditAgent",         lambda p: {"audit_id": "AUD-E2E", "status": "written"}),
        ("EscalationAgent",    lambda p: {"escalated": False}),
    ]
    mock_agents = []
    for name, fn in agent_specs:
        a = MagicMock()
        a.__class__ = type(name, (), {})
        a.__class__.__name__ = name
        a.execute = fn
        mock_agents.append(a)

    squad = BaseSquad(squad_id="ClaimsProcessingSquad", agents=mock_agents, orchestrator=None)
    squad.flow = [
        {"agent": "ClaimsTriageAgent",  "result_key": "triage"},
        {"agent": "AdjudicationAgent",  "result_key": "adjudication"},
        {"agent": "GuardAgent",         "result_key": "guard"},
        {"agent": "AuditAgent",         "result_key": "audit"},
        {"agent": "EscalationAgent",    "result_key": "escalation"},
    ]
    orch._squad = squad

    # 4. Execute the event handler directly (simulates what Kafka subscriber would call)
    result = orch.execute_flow(published)

    assert result["status"] == "completed"
    assert result["squad_id"] == "ClaimsProcessingSquad"
    assert result["triage"]["priority"] == "critical"
    assert result["adjudication"]["decision"] == "approve"
    assert result["guard"]["passed"] is True
    assert result["audit"]["audit_id"] == "AUD-E2E"
