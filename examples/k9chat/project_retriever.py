# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
ProjectRetriever — per-project file chunking, embedding, and retrieval
for K9Chat Projects.

Uses K9Retriever (VectorDBFactory + EmbeddingServiceFactory) exactly the
way dow-k9-aif's ViewGeneratorAgent does -- same store()/retrieve() calls,
same chunk-on-section-boundaries approach as the synthetic-corpus seeding
script (see dow-k9-aif/experiments/seed_synthetic_corpus.py, 2026-09-03).

Isolation model: one ChromaDB *collection* per project
(k9chat_project_{project_id}), not a shared collection filtered by
metadata. A metadata filter can have a bug in the filter logic and leak
another project's chunks into a retrieval call that never should have
seen them -- a separate collection makes that structurally impossible,
not just unlikely. This was a real, hard-learned lesson from dow-k9-aif's
FIREBIRD/SENTINEL cross-program contamination bug earlier in this same
session: retrieval that isn't structurally scoped will eventually leak.

Config (config.yaml)::

    vectordb:
      provider: chromadb          # default; no external DB required
      path: ./.chroma             # persisted locally, survives restarts
      embedding_provider: ollama
      embedding_model: nomic-embed-text
      embedding_endpoint: "${OLLAMA_BASE_URL:-http://localhost:11434}"

Each project's collection name is set per-retriever-instance, overriding
whatever `vectordb.collection` is in the base config.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from k9_aif_abb.k9_data.retrieval.k9_retriever import K9Retriever


def chunk_text(text: str, filename: str, max_chars: int = 1500) -> List[str]:
    """Split on paragraph boundaries (blank lines), merging short paragraphs
    up to max_chars and hard-splitting any single paragraph that's still
    too long on its own. Each chunk is prefixed with the filename for
    retrieval context, same pattern as seed_synthetic_corpus.py's
    per-document title prefix."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            for i in range(0, len(para), max_chars):
                chunks.append(para[i:i + max_chars])
            current = ""
    if current:
        chunks.append(current)

    return [f"[{filename}] {c}" for c in chunks]


class ProjectRetriever:
    """Lazily builds and caches one K9Retriever per project_id, each
    pointed at its own ChromaDB collection."""

    def __init__(self, base_config: Dict[str, Any]):
        self._base_config = base_config
        self._retrievers: Dict[str, K9Retriever] = {}

    def _collection_name(self, project_id: str) -> str:
        # ChromaDB collection names must be alnum/underscore/hyphen; a
        # project_id is already a uuid4 (hyphens only), safe as-is.
        return f"k9chat_project_{project_id}"

    def _get_retriever(self, project_id: str) -> K9Retriever:
        if project_id not in self._retrievers:
            cfg = copy.deepcopy(self._base_config)
            vdb_cfg = cfg.setdefault("vectordb", {})
            vdb_cfg.setdefault("provider", "chromadb")
            vdb_cfg["collection"] = self._collection_name(project_id)
            self._retrievers[project_id] = K9Retriever(config=cfg)
        return self._retrievers[project_id]

    def add_file(self, project_id: str, file_id: str, filename: str, text: str) -> int:
        """Chunk, embed, and store one file's content. Returns the number
        of chunks actually stored (0 if the embedding/vector backend isn't
        reachable -- caller should treat that as a real failure, not
        silently proceed as if the file were searchable)."""
        retriever = self._get_retriever(project_id)
        chunks = chunk_text(text, filename)
        stored = 0
        for i, chunk in enumerate(chunks):
            doc_id = f"{file_id}:{i}"
            ok = retriever.store(
                doc_id=doc_id,
                text=chunk,
                metadata={
                    "text": chunk,
                    "file_id": file_id,
                    "filename": filename,
                    "project_id": project_id,
                    "chunk_index": i,
                },
            )
            if ok:
                stored += 1
        return stored

    def remove_file(self, project_id: str, file_id: str, chunk_count: int) -> None:
        """Delete every chunk belonging to file_id. Requires chunk_count
        from ProjectManager's file record -- BaseVectorDB.delete() takes
        one doc_id at a time, no metadata-filtered bulk delete in the ABB
        contract, so exact IDs must be reconstructed here."""
        retriever = self._get_retriever(project_id)
        retriever._ensure_services()
        if retriever._vectordb is None:
            return
        for i in range(chunk_count):
            retriever._vectordb.delete(f"{file_id}:{i}")

    def delete_project(self, project_id: str, file_chunk_counts: Dict[str, int]) -> None:
        """Delete every file's chunks when a project is deleted."""
        for file_id, chunk_count in file_chunk_counts.items():
            self.remove_file(project_id, file_id, chunk_count)
        self._retrievers.pop(project_id, None)

    def retrieve_context(self, project_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Real semantic search against this project's files only. Returns
        [] if nothing is stored yet or the backend isn't reachable --
        caller falls back to no supplementary context, same as
        ViewGeneratorAgent's fallback behavior."""
        retriever = self._get_retriever(project_id)
        try:
            return retriever.retrieve(
                intent="k9chat_project_context",
                query=query,
                top_k=top_k,
            )
        except Exception:
            return []
