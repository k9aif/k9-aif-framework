"""
Provider-substitution latency experiment for the IEEE Access
resubmission ("An Integrated Ecosystem for Governed Enterprise Agentic
AI Systems"), Reviewer #1 Concern #1 / Reviewer #2 Concern #1
("provider substitution" item).

Question: does wrapping a task through K9-AIF's governance pipeline via
a different agent runtime (CrewAI, LangGraph) cost more, at the
framework/dispatch level, than running the identical task through a
native K9-AIF orchestrator? "Provider" here means agent runtime, not
LLM provider.

Design choice, disclosed directly: all three paths execute an
IDENTICAL trivial stub function as their "work" (no real LLM call).
This is deliberate, not a shortcut -- a real LLM call's latency
(hundreds of ms to seconds, highly variable) would dominate and mask
any framework-level difference between the three paths, which is
exactly the variable this experiment isolates. All three paths run
through the real governed dispatch pattern used in production: the
same ShieldGovernance configuration, the same apply_pre_governance() /
apply_post_governance() calls (via the same _run_coro_sync bridge the
real adapters use), the same publish_status() calls. Only the
"executor" each path wraps differs: a bare Python call (native), a
DummyCrew.kickoff() (CrewAI), a compiled StateGraph.invoke()
(LangGraph) -- exactly the same DummyCrew/EchoGraph pattern already
used in this repo's own test_crewai_adapter.py / test_langgraph_adapter.py.

The Claude Agent SDK adapter is not included here: unlike the other
two, it does not accept a pre-built external object to wrap -- it
always dispatches through a real Claude Agent SDK session, which
requires live API/CLI credentials and network access, and doesn't
support the same no-op-executor pattern used for a controlled,
network-free comparison. Measuring it would mean measuring live LLM
round-trip time, the exact confound this experiment is designed to
avoid for the other two.

Run: python k9_aif_abb/tests/experiments/adapter_dispatch_overhead.py
"""
import statistics
import time
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance

from k9_aif_abb.k9_adapters.crewai import K9CrewAIAdapter
from k9_aif_abb.k9_adapters.langgraph import K9LangGraphAdapter
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

N_RUNS = 100

GOVERNANCE_CONFIG = {
    "governance": {"provider": "shield"},
    "security": {
        "shield": {
            "enabled": True,
            "strict": False,
            "ingress": {"checks": ["PromptInjectionCheck"]},
            "egress": {"checks": ["OutputSanitizationCheck"]},
        }
    },
}


def make_governance():
    # A fresh instance per path, matching how a real deployment
    # constructs one governance object per orchestrator, not shared
    # mutable state across the three comparisons.
    return ShieldGovernance(config=GOVERNANCE_CONFIG)


def stub_work(message: str) -> str:
    """The identical 'work' every path performs -- deliberately trivial
    and constant-cost, so latency differences reflect dispatch overhead,
    not the work itself."""
    return f"stub output for: {message}"


# ---------------------------------------------------------------------
# Native K9-AIF path: bare orchestrator, no external runtime wrapped.
# Structurally identical to CrewAIOrchestratorAdapter/LangGraphOrchestratorAdapter
# (same base classes, same apply_pre_governance -> work -> apply_post_governance
# -> publish_status pattern) -- the only difference is what "work" calls.
# ---------------------------------------------------------------------
class NativeStubOrchestrator(BaseOrchestrator, BaseAdapter):
    def __init__(self, config=None, governance=None):
        BaseAdapter.__init__(self, adapter_name="NativeStubOrchestrator")
        BaseOrchestrator.__init__(self, config=config, governance=governance)

    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload or {}

    def adapt_output(self, result: Any) -> Any:
        return result

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from k9_aif_abb.k9_adapters.crewai.crewai_orchestrator_adapter import _run_coro_sync

        self.validate_payload(payload)
        native_input = self.adapt_input(payload)
        governed_input = _run_coro_sync(self.apply_pre_governance(native_input))
        self.publish_status("NativeSessionStarted", {"adapter": self.adapter_name})
        result = {"output": stub_work(governed_input.get("message", ""))}
        adapted = self.adapt_output(result)
        governed_output = _run_coro_sync(self.apply_post_governance(adapted))
        self.publish_status("NativeSessionCompleted", {"adapter": self.adapter_name})
        return governed_output


class DummyCrew:
    def kickoff(self, inputs=None):
        return {"output": stub_work((inputs or {}).get("message", ""))}


class _EchoState(TypedDict):
    message: str
    output: str


def build_echo_graph():
    def echo_node(state: _EchoState) -> dict:
        return {"output": stub_work(state.get("message", ""))}

    g = StateGraph(_EchoState)
    g.add_node("echo", echo_node)
    g.set_entry_point("echo")
    g.add_edge("echo", END)
    return g.compile()


def time_calls(fn, n=N_RUNS):
    samples_ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000)
    return samples_ms


def report(name, samples_ms):
    mean = statistics.mean(samples_ms)
    median = statistics.median(samples_ms)
    stdev = statistics.stdev(samples_ms) if len(samples_ms) > 1 else 0.0
    print(f"{name:<32} mean={mean:7.3f}ms  median={median:7.3f}ms  "
          f"stdev={stdev:6.3f}ms  min={min(samples_ms):6.3f}ms  max={max(samples_ms):6.3f}ms")
    return mean


if __name__ == "__main__":
    payload = {"message": "Summarize weather trends for Atlanta"}

    native = NativeStubOrchestrator(governance=make_governance())
    crewai_adapter = K9CrewAIAdapter(crew=DummyCrew(), governance=make_governance())
    langgraph_adapter = K9LangGraphAdapter(graph=build_echo_graph(), governance=make_governance())

    print(f"N={N_RUNS} calls per path, identical stub work, identical ShieldGovernance config.\n")

    native_samples = time_calls(lambda: native.execute_flow(dict(payload)))
    crewai_samples = time_calls(lambda: crewai_adapter.execute(dict(payload)))
    langgraph_samples = time_calls(lambda: langgraph_adapter.execute(dict(payload)))

    native_mean = report("Native K9-AIF orchestrator", native_samples)
    crewai_mean = report("CrewAI adapter (K9CrewAIAdapter)", crewai_samples)
    langgraph_mean = report("LangGraph adapter (K9LangGraphAdapter)", langgraph_samples)

    print(f"\nCrewAI adapter overhead vs. native:    {crewai_mean - native_mean:+.3f}ms "
          f"({(crewai_mean / native_mean - 1) * 100:+.1f}%)")
    print(f"LangGraph adapter overhead vs. native: {langgraph_mean - native_mean:+.3f}ms "
          f"({(langgraph_mean / native_mean - 1) * 100:+.1f}%)")
