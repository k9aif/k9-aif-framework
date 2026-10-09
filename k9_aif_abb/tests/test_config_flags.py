# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""On/off settings driven from .env arrive as strings ("true", "false") after
load_yaml expands ${VAR:-default}. Before 1.15.1 governance_from_config ignored
a string "true" (Guardian silently off), and enable_zero_trust / Shield's own
`enabled` read a string "false" as on. k9_inspect reads the raw YAML, so it judges
an unexpanded placeholder by its default."""

import textwrap

import pytest

from k9_aif_abb.k9_utils.config_flags import config_flag


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), ("true", True), ("TRUE", True), (" yes ", True), ("on", True), ("1", True),
    ("false", False), ("no", False), ("off", False), ("0", False), ("", False), (1, True), (0, False),
    ("${K9_GUARDIAN_ENABLED:-true}", True), ("${K9_SHIELD:-false}", False),
    ("${UNSET_NO_DEFAULT}", None), (None, None), ("maybe", None),
])
def test_config_flag(value, expected):
    assert config_flag(value) is expected


def test_default_when_unset_or_unknown():
    assert config_flag(None, True) is True
    assert config_flag("maybe", False) is False


SHIELD = {"enabled": "true", "ingress": {"checks": ["PromptInjectionCheck"]}, "egress": {"checks": []}}


def test_string_true_turns_on_shield_and_guardian():
    from k9_aif_abb.k9_core.governance.pipeline import governance_from_config
    from k9_aif_abb.k9_governance.chained_governance import ChainedGovernance
    gov = governance_from_config({"security": {"shield": SHIELD},
                                  "governance": {"guardian": {"enabled": "true"}}})
    assert isinstance(gov, ChainedGovernance)
    assert [type(s).__name__ for s in gov._stages] == ["ShieldGovernance", "GuardianGovernance"]


def test_string_false_turns_them_off():
    from k9_aif_abb.k9_core.governance.pipeline import governance_from_config
    from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance
    assert governance_from_config({"security": {"shield": {**SHIELD, "enabled": "false"}},
                                   "governance": {"guardian": {"enabled": "false"}}}) is None
    assert ShieldGovernance(config={"security": {"shield": {**SHIELD, "enabled": "false"}}}).enabled is False
    assert ShieldGovernance(config={"security": {"shield": {**SHIELD, "enabled": "true"}}}).enabled is True


def test_zero_trust_string_false_is_off():
    from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

    class Orch(BaseOrchestrator):
        def execute_flow(self, payload):
            return payload

    assert Orch(config={"enable_zero_trust": "false"}).enable_zero_trust is False
    assert Orch(config={"enable_zero_trust": "true"}).enable_zero_trust is True


def test_inspector_reads_env_driven_flags(tmp_path):
    from k9_aif_abb.k9_inspect import K9Inspector
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(textwrap.dedent("""
        inference: {llm_factory: {models: {fast: {model: m}}}}
        governance:
          guardian:
            enabled: "${K9_GUARDIAN_ENABLED:-true}"
        security:
          shield:
            enabled: "${K9_SHIELD_ENABLED:-true}"
            ingress: {checks: [InputSizeCheck, PromptInjectionCheck, PIIBoundaryCheck]}
            egress: {checks: [PIIBoundaryCheck]}
    """))
    ids = {f.rule_id for f in K9Inspector().inspect(tmp_path).findings}
    assert "K9-GOV-001" not in ids        # Shield counted as enabled
    assert "K9-GOV-004" not in ids        # Guardian counted as configured
    (tmp_path / "config" / "config.yaml").write_text(textwrap.dedent("""
        inference: {llm_factory: {models: {fast: {model: m}}}}
        governance:
          guardian:
            enabled: "${K9_GUARDIAN_ENABLED:-false}"
    """))
    assert "K9-GOV-004" in {f.rule_id for f in K9Inspector().inspect(tmp_path).findings}
