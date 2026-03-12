# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  RetrieverAgent (Hybrid)
# Performs governed multi-source retrieval (vector, SQL, file, or direct LLM reasoning).

import traceback
from typing import Dict, Any, List
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.persistence_factory import PersistenceFactory
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


class RetrieverAgent(BaseAgent):
    """SBB for hybrid knowledge retrieval  combines VectorDB, keyword, and LLM reasoning."""

    layer = "Retriever SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config=config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initializing RetrieverAgent (Hybrid Mode)")

        #  1 Persistence (VectorDB / SQL)
        try:
            self.persistence = PersistenceFactory.create(config=self.config, monitor=self.monitor)
            if self.persistence:
                self.logger.info(f"[{self.layer}] Persistence backend initialized.")
            else:
                self.logger.warning(f"[{self.layer}] No persistence backend returned by factory.")
        except Exception as e:
            self.logger.error(f"[{self.layer}] Persistence init failed: {e}")
            self.persistence = None

        #  2 LLM Fallback
        try:
            LLMFactory.bootstrap(self.config)
            self.llm = LLMFactory.get("general")
            self.logger.info(f"[{self.layer}] LLM initialized for reasoning fallback (provider={self.llm.provider})")
        except Exception as e:
            self.llm = None
            self.logger.warning(f"[{self.layer}] LLM fallback unavailable: {e}")

    # ------------------------------------------------------------------
    def _resolve_collection(self, payload: Dict[str, Any]) -> str:
        """Determines which knowledge base to query, if any."""
        if "collection" in payload:
            return payload["collection"]

        vectordb_cfg = self.config.get("vectordb", {})
        if "collection" in vectordb_cfg:
            return vectordb_cfg["collection"]

        query = payload.get("query", "").lower()
        if any(k in query for k in ["plan", "benefit", "coverage", "doctor", "acme"]):
            return "acme_health_knowledge"
        if any(k in query for k in ["framework", "k9", "aif", "governance"]):
            return "k9_aif_framework_v1_2"

        return "acme_health_knowledge"

    # ------------------------------------------------------------------
    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Hybrid retrieval entrypoint (vector, keyword, or LLM)."""
        query = payload.get("query", "").strip() or payload.get("message", "").strip()
        top_k = payload.get("top_k", 5)
        results: List[Dict[str, Any]] = []

        if not query:
            self.logger.warning(f"[{self.layer}]  Empty query received  nothing to process.")
            return {"results": [], "confidence": 0.0, "reply": " No query provided."}

        collection_name = self._resolve_collection(payload)
        self.logger.info(f"[{self.layer}]  Searching collection={collection_name}, query='{query}', top_k={top_k}")

        # 1 Try Vector Search
        try:
            if self.persistence:
                results = self.persistence.vector_search(query=query, top_k=top_k)
        except Exception as e:
            self.logger.warning(f"[{self.layer}]  Vector search failed: {e}")
            results = []

        # 2 Keyword fallback
        if (not results or len(results) == 0) and getattr(self.persistence, "client", None):
            self.logger.info(f"[{self.layer}]  Falling back to keyword scan for '{query}'")
            try:
                coll = self.persistence.client.get_or_create_collection(collection_name)
                docs = coll.get().get("documents", [])
                hits = [
                    {"text": doc[:500] + "...", "score": 0.35}
                    for doc in docs if any(word in doc.lower() for word in query.lower().split())
                ]
                results = hits[:top_k]
                self.logger.info(f"[{self.layer}]  Keyword fallback found {len(results)} hits.")
            except Exception as fe:
                self.logger.warning(f"[{self.layer}]  Keyword fallback failed: {fe}")

        # 3 LLM fallback reasoning
        if (not results or len(results) == 0) and self.llm:
            self.logger.info(f"[{self.layer}]  Using LLM fallback reasoning for '{query}'")
            try:
                llm_prompt = (
                    "You are the Retrieval Reasoning Agent for ACME HealthCare.\n"
                    "Answer factually and concisely from your model knowledge.\n\n"
                    f"Query: {query}\n\n"
                    "If you are unsure, reply with 'I'm not certain, but heres what I know:'"
                )
                response = await self.llm.ainvoke(llm_prompt)
                results = [{"text": response, "score": 0.9, "meta": {"source": "LLM"}}]
            except Exception as le:
                self.logger.error(f"[{self.layer}]  LLM fallback failed: {le}")
                traceback.print_exc()
                results = [{"text": " LLM reasoning failed.", "score": 0.0}]

        # 4 Confidence computation
        confidence = 0.0
        if results:
            scores = [r.get("score", 0.0) for r in results if isinstance(r, dict)]
            confidence = sum(scores) / len(scores) if scores else 0.0

        self.logger.info(f"[{self.layer}]  Retrieved {len(results)} results (confidence={confidence:.2f})")

        # Return results for structured chaining
        return {
            "results": results,
            "confidence": confidence,
            "reply": results[0]["text"] if results else " No relevant information found.",
        }