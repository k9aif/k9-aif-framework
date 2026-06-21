# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9EmbeddingAgent — OOB agent for generating embeddings and storing in VectorDB.

Reads chunks from the shared context (produced by K9DocPreprocessor),
generates embeddings via the configured embedding provider, and stores
them in the VectorDB via VectorDBFactory.
"""

import hashlib
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_data.vectordb_factory import VectorDBFactory


class K9EmbeddingAgent(BaseAgent):

    layer = "RAG K9EmbeddingAgent OOB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self._vectordb = None
        self._embed_client = None

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
        chunks = payload.get("chunks", [])

        if not chunks:
            self.logger.warning("[%s] No chunks in payload", self.layer)
            return {"agent": "K9EmbeddingAgent", "indexed": 0, "error": "no chunks"}

        self._ensure_vectordb()

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for chunk in chunks:
            text = chunk.get("text", "")
            if not text:
                continue

            doc_id = hashlib.md5(text.encode()).hexdigest()
            embedding = self._generate_embedding(text)

            if not embedding:
                self.logger.warning("[%s] Empty embedding for chunk %s", self.layer, chunk.get("index"))
                continue

            ids.append(doc_id)
            embeddings.append(embedding)
            documents.append(text)
            metadatas.append({
                "section": chunk.get("section", ""),
                "index": chunk.get("index", 0),
            })

        if ids:
            self._vectordb.insert_batch(ids, embeddings, documents, metadatas)

        self.publish_event({"type": "EmbeddingsGenerated", "count": len(ids)})
        self.logger.info("[%s] Indexed %d chunks into VectorDB", self.layer, len(ids))

        return {
            "agent": "K9EmbeddingAgent",
            "indexed": len(ids),
            "skipped": len(chunks) - len(ids),
        }
