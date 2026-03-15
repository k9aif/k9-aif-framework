# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary

from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


class RetrievalAgent(BaseAgent):
    """
    ABB RetrievalAgent
    ------------------
    Retrieves relevant knowledge or documents.
    Optionally rewrites the query via LLM before retrieval.
    """

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config or {})

        # Optional LLM rewriter
        llm_cfg = self.config.get("retrieval", {}).get("llm_rewriter")
        self.llm = LLMFactory.from_config(llm_cfg) if llm_cfg else None

    def execute(self, request: dict) -> dict:
        """
        Execute the retrieval step.

        Accepts either 'text' or 'query' as input to maximize
        compatibility across orchestrators and agents.
        """
        # Graceful handling for both key names
        text = request.get("text") or request.get("query") or ""
        if not text:
            self.log("[RetrievalAgent] Warning: empty input payload", level="WARNING")

        self.log(f"[RetrievalAgent] Incoming request: {text}")

        # Optional query rewrite through LLM
        if self.llm:
            rewritten = str(self.llm.generate(f"Rewrite query: {text}"))
            self.log(f"[RetrievalAgent] Rewritten query: {rewritten}")
            request["text"] = rewritten
        else:
            self.log("[RetrievalAgent] No LLM rewriter, using raw text")

        # ------------------------------------------------------------------
        # Stub retrieval (replace later with actual retrieval logic)
        # ------------------------------------------------------------------
        query_text = request.get("text") or text
        result = {
            "retrieved_docs": [f"Stubbed document for: {query_text}"],
            "query": query_text,
            "metadata": {"source": "mock_retrieval"},
        }

        self.log(f"[RetrievalAgent] Retrieved docs: {result['retrieved_docs']}")
        return result