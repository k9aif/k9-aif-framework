from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Coroutine, Dict, Optional

from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator


def _run_coro_sync(coro: "Coroutine[Any, Any, Any]") -> Any:
    """
    Execute an async coroutine from synchronous code -- safe whether or not
    an event loop is already running on the calling thread. Same helper,
    same reason, as K9ModelRouter's (k9_inference/routers/k9_model_router.py)
    and CrewAIOrchestratorAdapter's: apply_pre/post_governance() are async,
    execute_flow() is a sync contract.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class LangGraphOrchestratorAdapter(BaseOrchestrator, BaseAdapter):
    """
    Adapter that wraps a compiled LangGraph (a CompiledStateGraph, the
    result of StateGraph.compile()) and exposes it through K9-AIF
    orchestration contracts.

    Wrapped at the Orchestrator layer, not the Agent layer: a compiled
    graph is itself a multi-node orchestrating construct with its own
    internal execution flow (nodes, edges, conditional branching), the
    same reasoning that put CrewAI's Crew here rather than at the Agent
    layer where the Claude Agent SDK sits (Architecture_Guide.md,
    Pet Store Agentic, Principle 1).

    Governance is invoked unconditionally on every call, exactly like
    every other K9-AIF orchestrator -- built in from this adapter's first
    version, not added after the fact. (The CrewAI adapter's first
    shipped version omitted this; see its own module for the corrected
    history. Not repeating that here.)
    """

    def __init__(
        self,
        graph: Any,
        name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        governance: Optional[Any] = None,
    ) -> None:
        BaseAdapter.__init__(self, adapter_name=name or "LangGraphOrchestratorAdapter")
        BaseOrchestrator.__init__(self, config=config, governance=governance)
        self.graph = graph

    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thin pass-through. LangGraphPayloadMapper.to_langgraph_input() is
        the only place that normalizes input, called once at the facade
        layer (K9LangGraphAdapter.execute()). Applying the same
        normalization a second time here would re-wrap an already-
        normalized payload -- the exact double-normalization defect the
        CrewAI adapter shipped with and later had removed from both its
        adapt_input() and adapt_output(). Not repeating it here.
        """
        return payload or {}

    def adapt_output(self, result: Any) -> Any:
        """Thin pass-through -- see adapt_input() docstring; same reasoning,
        output side. LangGraphPayloadMapper.from_langgraph_output() is the
        only normalization point."""
        return result

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_payload(payload)
        graph_input = self.adapt_input(payload)

        governed_input = _run_coro_sync(self.apply_pre_governance(graph_input))

        self.publish_status("LangGraphSessionStarted", {"adapter": self.adapter_name})

        result = self.graph.invoke(governed_input)

        adapted = self.adapt_output(result)
        governed_output = _run_coro_sync(self.apply_post_governance(adapted))

        self.publish_status("LangGraphSessionCompleted", {"adapter": self.adapter_name})

        return governed_output
