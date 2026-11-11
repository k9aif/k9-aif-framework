# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.26: Zero Trust enabled but its package unavailable fails closed outside development/test.

Before 1.26 BaseOrchestrator and BaseRouter allowed every request (decision UNAVAILABLE_BYPASS)
in every environment. Now production refuses to construct, and a flag switched on after
construction denies. Development/test keep the logged allow.
"""
from typing import Any, Dict

import pytest

from k9_aif_abb.k9_core.orchestration import base_orchestrator as orch_mod
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.router import base_router as router_mod
from k9_aif_abb.k9_core.router.base_router import BaseRouter
from k9_aif_abb.tests.test_framework import RealGovernance


class _Orchestrator(BaseOrchestrator):
    layer = "ZT Test Orchestrator"

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class _Router(BaseRouter):
    layer = "ZT Test Router"

    def route(self, payload):
        return payload


@pytest.fixture
def zt_missing(monkeypatch):
    monkeypatch.setattr(orch_mod, "ZERO_TRUST_AVAILABLE", False)
    monkeypatch.setattr(orch_mod, "ZERO_TRUST_IMPORT_ERROR", "ImportError('simulated')")
    monkeypatch.setattr(router_mod, "ZERO_TRUST_AVAILABLE", False)
    monkeypatch.setattr(router_mod, "ZERO_TRUST_IMPORT_ERROR", "ImportError('simulated')")


@pytest.mark.parametrize("cls", [_Orchestrator, _Router])
def test_production_refuses_to_start(cls, zt_missing, monkeypatch):
    monkeypatch.setenv("K9_ENV", "production")
    with pytest.raises(RuntimeError, match="Zero Trust is enabled"):
        cls(governance=RealGovernance(), enable_zero_trust=True)


@pytest.mark.parametrize("cls", [_Orchestrator, _Router])
def test_unset_env_counts_as_production(cls, zt_missing, monkeypatch):
    monkeypatch.delenv("K9_ENV", raising=False)
    with pytest.raises(RuntimeError):
        cls(governance=RealGovernance(), enable_zero_trust=True)


@pytest.mark.parametrize("cls", [_Orchestrator, _Router])
def test_development_allows_and_logs(cls, zt_missing, monkeypatch, caplog):
    monkeypatch.setenv("K9_ENV", "development")
    comp = cls(governance=RealGovernance(), enable_zero_trust=True)
    out = comp.apply_zero_trust({"q": "x"})
    assert out["allowed"] is True and out["decision"] == "UNAVAILABLE_BYPASS"
    assert any("unavailable" in r.message for r in caplog.records)


@pytest.mark.parametrize("cls", [_Orchestrator, _Router])
def test_flag_switched_on_later_denies_in_production(cls, zt_missing, monkeypatch):
    monkeypatch.setenv("K9_ENV", "production")
    comp = cls(governance=RealGovernance(), enable_zero_trust=False)
    comp.enable_zero_trust = True
    out = comp.apply_zero_trust({"q": "x"})
    assert out["allowed"] is False and out["decision"] == "UNAVAILABLE_DENY"


@pytest.mark.parametrize("cls", [_Orchestrator, _Router])
def test_disabled_is_unchanged(cls, zt_missing, monkeypatch):
    monkeypatch.setenv("K9_ENV", "production")
    out = cls(governance=RealGovernance()).apply_zero_trust({"q": "x"})
    assert out["allowed"] is True and out["decision"] == "BYPASSED"
