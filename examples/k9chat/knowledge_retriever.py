# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
KnowledgeRetriever — always-on retrieval against a single fixed
ChromaDB collection seeded with the real K9-AIF framework and K9X
ecosystem documentation (CLAUDE.md/SKILLS.md/README.md files).

Deliberately NOT built on ProjectRetriever's per-project-id scheme: this
isn't something a user creates/manages like a Project (no name,
instructions, or file list a user edits) -- it's one fixed, always-queried
collection every chat turn retrieves from regardless of which Project (if
any) is selected. Population happens out-of-band via seed_knowledge_base.py,
not through the /projects file-upload API.

Config (config.yaml)::

    vectordb:
      provider: chromadb
      path: ./.chroma
      embedding_provider: ollama
      embedding_model: nomic-embed-text
      embedding_endpoint: "${OLLAMA_BASE_URL:-http://localhost:11434}"
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from k9_aif_abb.k9_data.retrieval.k9_retriever import K9Retriever

COLLECTION_NAME = "k9x_knowledge_base"


class KnowledgeRetriever:
    """Lazily builds one K9Retriever pointed at the fixed knowledge collection."""

    def __init__(self, base_config: Dict[str, Any]):
        cfg = copy.deepcopy(base_config)
        vdb_cfg = cfg.setdefault("vectordb", {})
        vdb_cfg.setdefault("provider", "chromadb")
        vdb_cfg["collection"] = COLLECTION_NAME
        self._retriever = K9Retriever(config=cfg)

    def store_chunk(self, doc_id: str, text: str, metadata: Dict[str, Any]) -> bool:
        return self._retriever.store(doc_id=doc_id, text=text, metadata=metadata)

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Real semantic search against the knowledge base. Returns [] if
        nothing is stored yet (seeder hasn't run) or the backend isn't
        reachable -- caller falls back to no supplementary context, same
        fail-open behavior as ProjectRetriever."""
        try:
            return self._retriever.retrieve(
                intent="k9chat_knowledge_context",
                query=query,
                top_k=top_k,
            )
        except Exception:
            return []
