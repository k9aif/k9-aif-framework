"""
Primary K9-AIF facade for LangGraph integration.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .langgraph_orchestrator_adapter import LangGraphOrchestratorAdapter
from .langgraph_payload_mapper import LangGraphPayloadMapper


class K9LangGraphAdapter:
    """
    OOB facade for integrating a compiled LangGraph into K9-AIF.

    Responsibilities:
    - accept K9-AIF-style payloads
    - normalize payloads for LangGraph
    - invoke the wrapped compiled graph via adapter
    - normalize the response back to K9-AIF format
    """

    def __init__(
        self,
        graph: Any,
        mapper: Optional[LangGraphPayloadMapper] = None,
        orchestrator_adapter: Optional[LangGraphOrchestratorAdapter] = None,
        config: Optional[Dict[str, Any]] = None,
        governance: Optional[Any] = None,
    ) -> None:
        self.mapper = mapper or LangGraphPayloadMapper()
        self.orchestrator_adapter = orchestrator_adapter or LangGraphOrchestratorAdapter(
            graph=graph, config=config, governance=governance
        )

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main adapter entrypoint for K9-AIF callers.
        """
        graph_input = self.mapper.to_langgraph_input(payload)
        result = self.orchestrator_adapter.execute_flow(graph_input)
        return self.mapper.from_langgraph_output(result)
