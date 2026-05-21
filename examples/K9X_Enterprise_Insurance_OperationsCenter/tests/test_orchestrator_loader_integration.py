# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — test_orchestrator_loader_integration.py
#
# Validates:
# - OrchestratorLoader imports from k9_aif_abb.k9_orchestrators.orchestrator_loader
# - OrchestratorLoader.register() accepts EOC orchestrator classes
# - OrchestratorLoader.load() creates orchestrator instances from config dict
# - OrchestratorLoader.load() uses SquadLoader when squad config is provided
# - Missing/invalid orchestrator type raises ValueError clearly

from unittest.mock import MagicMock, patch
import pytest

from k9_aif_abb.k9_orchestrators.orchestrator_loader import OrchestratorLoader
from k9_aif_abb.k9_squad.squad_loader import SquadLoader

from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.claims_processing_orchestrator import ClaimsProcessingOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.risk_assessment_orchestrator import RiskAssessmentOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.audit_compliance_orchestrator import AuditComplianceOrchestrator


# ---------------------------------------------------------------------------
# Import validation
# ---------------------------------------------------------------------------

def test_orchestrator_loader_imports_from_correct_abb_path():
    import k9_aif_abb.k9_orchestrators.orchestrator_loader as mod
    assert hasattr(mod, "OrchestratorLoader")


def test_orchestrator_loader_class_exists():
    assert OrchestratorLoader is not None


# ---------------------------------------------------------------------------
# register() — accept EOC orchestrator classes
# ---------------------------------------------------------------------------

def test_register_claims_orchestrator():
    loader = OrchestratorLoader()
    loader.register("claims", ClaimsProcessingOrchestrator)
    assert "claims" in loader.registry
    assert loader.registry["claims"] is ClaimsProcessingOrchestrator


def test_register_multiple_orchestrators():
    loader = OrchestratorLoader()
    loader.register("claims",  ClaimsProcessingOrchestrator)
    loader.register("risk",    RiskAssessmentOrchestrator)
    loader.register("audit",   AuditComplianceOrchestrator)
    assert len(loader.registry) == 3


# ---------------------------------------------------------------------------
# load() — creates orchestrator instances from config dict
# ---------------------------------------------------------------------------

def test_load_creates_orchestrator_instance():
    loader = OrchestratorLoader(registry={"claims": ClaimsProcessingOrchestrator})
    cfg = {"type": "claims", "id": "claims_orch"}
    instance = loader.load(cfg)
    assert isinstance(instance, ClaimsProcessingOrchestrator)


def test_load_passes_config_to_orchestrator():
    loader = OrchestratorLoader(registry={"audit": AuditComplianceOrchestrator})
    cfg = {"type": "audit", "id": "audit_orch", "custom_key": "custom_value"}
    instance = loader.load(cfg)
    # config is passed as the full config dict
    assert instance.config.get("type") == "audit"
    assert instance.config.get("id") == "audit_orch"


def test_load_raises_for_missing_type():
    loader = OrchestratorLoader(registry={"claims": ClaimsProcessingOrchestrator})
    with pytest.raises(ValueError, match="type"):
        loader.load({"id": "no_type_here"})


def test_load_raises_for_unregistered_type():
    loader = OrchestratorLoader(registry={"claims": ClaimsProcessingOrchestrator})
    with pytest.raises(ValueError, match="No orchestrator registered for type"):
        loader.load({"type": "nonexistent_type"})


def test_load_with_empty_registry_raises():
    loader = OrchestratorLoader()
    with pytest.raises(ValueError):
        loader.load({"type": "claims"})


# ---------------------------------------------------------------------------
# load() with SquadLoader — squads attached when configured
# ---------------------------------------------------------------------------

def test_load_with_squad_loader_calls_squad_loader():
    mock_squad_loader = MagicMock(spec=SquadLoader)
    mock_squad_loader.load.return_value = MagicMock()

    loader = OrchestratorLoader(
        registry={"claims": ClaimsProcessingOrchestrator},
        squad_loader=mock_squad_loader,
    )
    cfg = {
        "type": "claims",
        "id": "claims_orch",
        "squads": [{"name": "ClaimsProcessingSquad"}],
    }
    instance = loader.load(cfg)
    mock_squad_loader.load.assert_called_once()
    assert isinstance(instance, ClaimsProcessingOrchestrator)


def test_load_without_squads_does_not_call_squad_loader():
    mock_squad_loader = MagicMock(spec=SquadLoader)
    loader = OrchestratorLoader(
        registry={"claims": ClaimsProcessingOrchestrator},
        squad_loader=mock_squad_loader,
    )
    cfg = {"type": "claims", "id": "claims_orch"}
    loader.load(cfg)
    mock_squad_loader.load.assert_not_called()


# ---------------------------------------------------------------------------
# All 7 EOC orchestrators can be registered and loaded
# ---------------------------------------------------------------------------

from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.document_intelligence_orchestrator import DocumentIntelligenceOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.policy_management_orchestrator import PolicyManagementOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.catastrophe_response_orchestrator import CatastropheResponseOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.customer_service_orchestrator import CustomerServiceOrchestrator

ALL_ORCHESTRATORS = {
    "claims":       ClaimsProcessingOrchestrator,
    "documents":    DocumentIntelligenceOrchestrator,
    "risk":         RiskAssessmentOrchestrator,
    "policy":       PolicyManagementOrchestrator,
    "catastrophe":  CatastropheResponseOrchestrator,
    "customer":     CustomerServiceOrchestrator,
    "audit":        AuditComplianceOrchestrator,
}

@pytest.mark.parametrize("orch_type,orch_cls", ALL_ORCHESTRATORS.items())
def test_all_orchestrators_register_and_load(orch_type, orch_cls):
    loader = OrchestratorLoader(registry={orch_type: orch_cls})
    instance = loader.load({"type": orch_type, "id": f"{orch_type}_orch"})
    assert instance is not None
    assert isinstance(instance, orch_cls)
