# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — test_project_structure.py
#
# Validates that required folders, files, and YAML configs exist.

from pathlib import Path
import yaml
import pytest

EOC = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Required directories
# ---------------------------------------------------------------------------
REQUIRED_DIRS = [
    "agents/src",
    "agents/yaml",
    "squads/src",
    "squads/yaml",
    "orchestrators",
    "router",
    "config",
    "utils",
    "tests",
]

@pytest.mark.parametrize("folder", REQUIRED_DIRS)
def test_required_directory_exists(folder):
    assert (EOC / folder).is_dir(), f"Missing directory: {folder}"


# ---------------------------------------------------------------------------
# Required Python source files
# ---------------------------------------------------------------------------
REQUIRED_PYTHON_FILES = [
    # Agents
    "agents/src/claims_triage_agent.py",
    "agents/src/adjudication_agent.py",
    "agents/src/guard_agent.py",
    "agents/src/escalation_agent.py",
    "agents/src/audit_agent.py",
    "agents/src/document_extractor_agent.py",
    "agents/src/fraud_detection_agent.py",
    "agents/src/graph_sync_agent.py",
    # Orchestrators
    "orchestrators/claims_processing_orchestrator.py",
    "orchestrators/document_intelligence_orchestrator.py",
    "orchestrators/risk_assessment_orchestrator.py",
    "orchestrators/policy_management_orchestrator.py",
    "orchestrators/catastrophe_response_orchestrator.py",
    "orchestrators/customer_service_orchestrator.py",
    "orchestrators/audit_compliance_orchestrator.py",
    # Router
    "router/eoc_router.py",
    "router/eoc_model_router.py",
    # Utils
    "utils/config_loader.py",
    "utils/systems_check.py",
    "utils/bootstrap.py",
]

@pytest.mark.parametrize("filepath", REQUIRED_PYTHON_FILES)
def test_required_python_file_exists(filepath):
    assert (EOC / filepath).is_file(), f"Missing file: {filepath}"


# ---------------------------------------------------------------------------
# Required YAML configs
# ---------------------------------------------------------------------------
REQUIRED_YAML_FILES = [
    "config/config.yaml",
    "config/squads.yaml",
    "config/governance.yaml",
    "config/flows.yaml",
    # Agent YAMLs
    "agents/yaml/claims_triage_agent.yaml",
    "agents/yaml/adjudication_agent.yaml",
    "agents/yaml/guard_agent.yaml",
    "agents/yaml/audit_agent.yaml",
    # Squad YAMLs
    "squads/yaml/claims_processing_squad.yaml",
    "squads/yaml/document_intelligence_squad.yaml",
    "squads/yaml/risk_assessment_squad.yaml",
    "squads/yaml/policy_management_squad.yaml",
    "squads/yaml/catastrophe_response_squad.yaml",
    "squads/yaml/customer_service_squad.yaml",
    "squads/yaml/audit_compliance_squad.yaml",
]

@pytest.mark.parametrize("yamlpath", REQUIRED_YAML_FILES)
def test_required_yaml_file_exists(yamlpath):
    assert (EOC / yamlpath).is_file(), f"Missing YAML: {yamlpath}"


# ---------------------------------------------------------------------------
# squads.yaml has required structure for SquadLoader
# ---------------------------------------------------------------------------
def test_squads_yaml_has_squads_key():
    data = yaml.safe_load((EOC / "config/squads.yaml").read_text())
    assert "squads" in data, "config/squads.yaml must have top-level 'squads' key"


def test_squads_yaml_contains_all_squads():
    data = yaml.safe_load((EOC / "config/squads.yaml").read_text())
    squads = data.get("squads", {})
    expected = {
        "ClaimsProcessingSquad",
        "DocumentIntelligenceSquad",
        "RiskAssessmentSquad",
        "PolicyManagementSquad",
        "CatastropheResponseSquad",
        "CustomerServiceSquad",
        "AuditComplianceSquad",
    }
    missing = expected - set(squads.keys())
    assert not missing, f"squads.yaml missing squads: {missing}"


def test_each_squad_has_orchestrator_and_agents():
    data = yaml.safe_load((EOC / "config/squads.yaml").read_text())
    for squad_id, cfg in data.get("squads", {}).items():
        assert "orchestrator" in cfg, f"{squad_id}: missing 'orchestrator'"
        assert "agents" in cfg and len(cfg["agents"]) > 0, f"{squad_id}: missing 'agents'"


# ---------------------------------------------------------------------------
# __init__.py files exist for all packages
# ---------------------------------------------------------------------------
PACKAGE_INITS = [
    "agents/__init__.py",
    "agents/src/__init__.py",
    "squads/__init__.py",
    "squads/src/__init__.py",
    "orchestrators/__init__.py",
    "router/__init__.py",
    "utils/__init__.py",
]

@pytest.mark.parametrize("initfile", PACKAGE_INITS)
def test_package_init_exists(initfile):
    assert (EOC / initfile).is_file(), f"Missing __init__.py: {initfile}"
