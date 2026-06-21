# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9RetrievalAgent — OOB agent for RAG retrieval from VectorDB.

Takes a query from the payload, generates a query embedding,
searches the VectorDB for top-k similar chunks, and writes
the retrieved context to the shared squad context.
Downstream reasoning agents use the retrieved context — not the raw document.
"""

from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_data.vectordb_factory import VectorDBFactory


class K9RetrievalAgent(BaseAgent):

    layer = "RAG K9RetrievalAgent OOB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self._vectordb = None
        self._embed_client = None
        self.top_k = self.config.get("top_k", 5)

    def _ensure_vectordb(self):
        if self._vectordb is None:
            self._vectordb = VectorDBFactory.from_config(self.config)

    def _ensure_embed_client(self):
        if self._embed_client is not None:
            return
        vdb_cfg = self.config.get("vectordb", {})
        provider = vdb_cfg.get("embedding_provider", "ollama")

        if provider == "ollama":
            try:
                from ollama import Client
            except ImportError as exc:
                raise RuntimeError("pip install ollama required for embedding") from exc
            host = vdb_cfg.get("embedding_endpoint", self.config.get("inference", {}).get("llm_factory", {}).get("base_url", "http://localhost:11434"))
            self._embed_client = Client(host=host)
            self._embed_model = vdb_cfg.get("embedding_model", "nomic-embed-text")
            self._embed_type = "ollama"
        else:
            raise ValueError(f"Unsupported embedding provider: {provider}")

    def _generate_embedding(self, text: str) -> List[float]:
        self._ensure_embed_client()
        if self._embed_type == "ollama":
            result = self._embed_client.embeddings(model=self._embed_model, prompt=text)
            return result.get("embedding", [])
        return []

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = payload.get("query", "") or payload.get("question", "") or payload.get("prompt", "")

        if not query:
            self.logger.warning("[%s] No query in payload", self.layer)
            return {"agent": "K9RetrievalAgent", "retrieved": [], "count": 0, "error": "no query"}

        self._ensure_vectordb()
        query_embedding = self._generate_embedding(query)

        if not query_embedding:
            self.logger.error("[%s] Failed to generate query embedding", self.layer)
            return {"agent": "K9RetrievalAgent", "retrieved": [], "count": 0, "error": "embedding failed"}

        hits = self._vectordb.search(query_embedding, top_k=self.top_k)

        context_text = "\n\n---\n\n".join(h.get("text", "") for h in hits if h.get("text"))

        self.publish_event({"type": "RetrievalCompleted", "query": query[:100], "hits": len(hits)})
        self.logger.info("[%s] Retrieved %d chunks for query: %s", self.layer, len(hits), query[:80])

        return {
            "agent": "K9RetrievalAgent",
            "retrieved": hits,
            "count": len(hits),
            "context": context_text,
            "query": query,
        }
