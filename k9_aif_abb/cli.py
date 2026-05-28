# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — CLI entry point
"""
k9aif — command line interface for K9-AIF framework verification.

Usage after pip install:
    k9aif verify      # smoke test — no LLM needed
    k9aif version     # show version
    k9aif info        # show installed components
"""

from __future__ import annotations
import sys


def verify():
    """Run a framework smoke test — no LLM or external services needed."""
    print("K9-AIF Framework — Smoke Test")
    print("=" * 40)

    passed = 0
    failed = 0

    def check(label, fn):
        nonlocal passed, failed
        try:
            fn()
            print(f"  ✓  {label}")
            passed += 1
        except Exception as exc:
            print(f"  ✗  {label}: {exc}")
            failed += 1

    # ABB contracts
    check("BaseAgent import", lambda: __import__(
        "k9_aif_abb.k9_core.agent.base_agent", fromlist=["BaseAgent"]))
    check("BaseRouter import", lambda: __import__(
        "k9_aif_abb.k9_core.router.base_router", fromlist=["BaseRouter"]))
    check("BaseOrchestrator import", lambda: __import__(
        "k9_aif_abb.k9_core.orchestration.base_orchestrator", fromlist=["BaseOrchestrator"]))
    check("BaseSquad import", lambda: __import__(
        "k9_aif_abb.k9_squad.base_squad", fromlist=["BaseSquad"]))

    # Factories
    check("LLMFactory import", lambda: __import__(
        "k9_aif_abb.k9_factories.llm_factory", fromlist=["LLMFactory"]))
    check("ModelRouterFactory import", lambda: __import__(
        "k9_aif_abb.k9_factories.model_router_factory", fromlist=["ModelRouterFactory"]))
    check("AgentRegistry import", lambda: __import__(
        "k9_aif_abb.k9_agents.registry.agent_registry", fromlist=["AgentRegistry"]))

    # Governance
    check("Governance pipeline import", lambda: __import__(
        "k9_aif_abb.k9_core.governance.pipeline", fromlist=["require_governance"]))

    # Inference
    check("InferenceRequest import", lambda: __import__(
        "k9_aif_abb.k9_inference.models.inference_request", fromlist=["InferenceRequest"]))

    # CrewAI adapter
    check("K9CrewAIAdapter import", lambda: __import__(
        "k9_aif_abb.k9_adapters.crewai.k9_crewai_adapter", fromlist=["K9CrewAIAdapter"]))

    # Validation loop
    check("BaseValidationLoopAgent import", lambda: __import__(
        "k9_aif_abb.k9_agents.validation", fromlist=["BaseValidationLoopAgent"]))

    # Governance enforcement
    def _test_governance():
        from k9_aif_abb.k9_core.governance.pipeline import require_governance, NoopGovernance
        gov = require_governance(None, "development")
        assert isinstance(gov, NoopGovernance)

    check("Governance enforcement (dev mode)", _test_governance)

    # Agent registry round-trip
    def _test_registry():
        from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
        from k9_aif_abb.k9_core.agent.base_agent import BaseAgent

        class _TestAgent(BaseAgent):
            layer = "TestAgent"
            def execute(self, payload):
                return {"ok": True}

        registry = AgentRegistry()
        registry.register("_TestAgent", _TestAgent)
        agent = registry.create("_TestAgent")
        result = agent.execute({})
        assert result["ok"] is True

    check("Agent registry — register + create + execute", _test_registry)

    print()
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print()
        print("K9-AIF is installed correctly and ready to use.")
        print("Next step: see docs/getting-started.md")
    else:
        print()
        print("Some checks failed. Run with Python 3.11+ and retry.")
        sys.exit(1)


def version():
    try:
        from importlib.metadata import version as pkg_version
        print(f"k9_aif_abb {pkg_version('k9_aif_abb')}")
    except Exception:
        print("k9_aif_abb (version unknown)")


def info():
    print("K9-AIF Framework")
    print("Architecture-First Framework for Governed, Modular Agentic AI Systems")
    print()
    print("Framework:   https://github.com/k9aif/k9-aif-framework")
    print("Docs:        https://k9x.ai")
    print("Blog:        https://blog.k9x.ai")
    print()
    print("Key ABBs:")
    print("  BaseAgent, BaseRouter, BaseOrchestrator, BaseSquad")
    print("  BaseValidationLoopAgent, BaseCriticActorAgent")
    print("  BaseModelRouter, BaseGovernance, BaseSecretManager")
    print()
    print("Run 'k9aif verify' to confirm installation.")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"

    if cmd == "verify":
        verify()
    elif cmd == "version":
        version()
    elif cmd == "info":
        info()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: k9aif [verify|version|info]")
        sys.exit(1)


if __name__ == "__main__":
    main()
