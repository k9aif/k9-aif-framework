# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
ProjectManager — CRUD for K9Chat Projects, backed by SQLitePersistence.

A Project groups: a name, optional custom instructions (system prompt),
and a set of uploaded files whose chunked content is available as context
to every chat session associated with that project — the same shape as
Claude Desktop's Projects feature.

Storage choice: SQLitePersistence (k9_aif_abb/k9_persistence/sqlite_persistence.py)
via PersistenceFactory, not CacheFactory's in_memory adapter. Project data
is the kind of thing a user expects to survive an app restart -- unlike
chat_agent.py's session history (deliberately ephemeral, TTL-bound), so
in_memory was the wrong fit. Considered and declined for this same reason:
- Redis (CacheFactory's other option): a real instance exists at
  192.168.1.98:6379, but requires a password not documented anywhere in
  this workspace (checked: only placeholder "changeme"/"redis" values in
  .env.sample templates) -- not guessing at a live service's credentials.
- PostgreSQL: no Postgres-backed persistence adapter exists in the
  framework at all (PersistenceFactory only has "sqlite" registered) --
  would mean building a new adapter from scratch for marginal benefit
  over SQLite, which already gives real durability with zero external
  server or credentials.
- Milvus: VectorDBFactory has a real (non-stub) MilvusAdapter and the
  user has a container available to re-enable, but that's for the file
  *vector* store (see project_retriever.py), not project *metadata* --
  ChromaDB (already zero-setup, embedded, persisted to disk) fits
  k9chat's own "lightweight example" framing better than standing up a
  separate Milvus server for this.
SQLite needed one real bug fixed to be usable via the factory at all --
see PersistenceFactory.create()'s config-kwarg mismatch with
SQLitePersistence.__init__(), fixed in the same commit as this file.

Key layout (mirrors chat_agent.py's k9chat:history:{session_id} convention,
using load_state/save_state instead of get/set):
    k9chat:projects:index          -> {"project_ids": [...]}
    k9chat:project:{project_id}    -> project record dict
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_factories.persistence_factory import PersistenceFactory


_INDEX_KEY = "k9chat:projects:index"


def _project_key(project_id: str) -> str:
    return f"k9chat:project:{project_id}"


class ProjectNotFoundError(Exception):
    pass


def build_persistence(base_config: Dict[str, Any]):
    """PersistenceFactory.create() defaults db_path to a relative
    'k9_aif_state.db' (cwd-dependent -- would land in whatever directory
    uvicorn happens to be launched from). Anchor it to this example's own
    directory instead, matching how config.yaml/​.env are already loaded
    relative to BASE_DIR elsewhere in this package."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Use `or`, not .get(key, default) -- config.yaml's projects.db_path
    # is "${K9CHAT_PROJECTS_DB:-}", which expands to an empty string (not
    # an absent key) when the env var isn't set, and .get()'s default only
    # fires on a missing key, not a falsy value.
    db_path = base_config.get("projects", {}).get("db_path") or os.path.join(
        base_dir, "k9chat_projects.db"
    )
    return PersistenceFactory.create({"persistence": {"backend": "sqlite", "db_path": db_path}})


class ProjectManager:
    """CRUD for Projects, plus file-membership bookkeeping.

    Does not itself chunk/embed files -- that's ProjectRetriever's job.
    This class only tracks which file_ids belong to which project, so
    ProjectRetriever knows what to delete when a project or file is
    removed, and the UI knows what to list.
    """

    def __init__(self, persistence):
        self._store = persistence

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------
    def _read_index(self) -> List[str]:
        record = self._store.load_state(_INDEX_KEY)
        if not record:
            return []
        return record.get("project_ids", [])

    def _write_index(self, project_ids: List[str]) -> None:
        self._store.save_state(_INDEX_KEY, {"project_ids": project_ids})

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_project(self, name: str, instructions: str = "") -> Dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = time.time()
        record = {
            "project_id": project_id,
            "name": name,
            "instructions": instructions,
            "created_at": now,
            "updated_at": now,
            "file_ids": [],
            "files": {},
        }
        self._store.save_state(_project_key(project_id), record)

        index = self._read_index()
        index.append(project_id)
        self._write_index(index)

        return record

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._store.load_state(_project_key(project_id))

    def list_projects(self) -> List[Dict[str, Any]]:
        projects = []
        for project_id in self._read_index():
            record = self.get_project(project_id)
            if record is not None:
                projects.append(record)
        return projects

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = self.get_project(project_id)
        if record is None:
            raise ProjectNotFoundError(project_id)
        if name is not None:
            record["name"] = name
        if instructions is not None:
            record["instructions"] = instructions
        record["updated_at"] = time.time()
        self._store.save_state(_project_key(project_id), record)
        return record

    def delete_project(self, project_id: str) -> Dict[str, int]:
        """Remove the project record and index entry. Returns
        {file_id: chunk_count} for the files it owned, so the caller
        (app.py) can tell ProjectRetriever to delete their vectors --
        this class doesn't own that store."""
        record = self.get_project(project_id)
        if record is None:
            raise ProjectNotFoundError(project_id)

        self._store.delete_state(_project_key(project_id))
        index = self._read_index()
        if project_id in index:
            index.remove(project_id)
            self._write_index(index)

        return {
            file_id: meta.get("chunk_count", 0)
            for file_id, meta in record.get("files", {}).items()
        }

    # ------------------------------------------------------------------
    # File membership
    # ------------------------------------------------------------------
    def add_file(self, project_id: str, file_id: str, filename: str, chunk_count: int) -> Dict[str, Any]:
        record = self.get_project(project_id)
        if record is None:
            raise ProjectNotFoundError(project_id)
        record.setdefault("file_ids", []).append(file_id)
        record.setdefault("files", {})[file_id] = {
            "filename": filename,
            "chunk_count": chunk_count,
        }
        record["updated_at"] = time.time()
        self._store.save_state(_project_key(project_id), record)
        return record

    def remove_file(self, project_id: str, file_id: str) -> int:
        """Returns the chunk_count that was recorded for this file, so
        the caller can tell ProjectRetriever exactly how many vector rows
        to delete."""
        record = self.get_project(project_id)
        if record is None:
            raise ProjectNotFoundError(project_id)
        chunk_count = record.get("files", {}).get(file_id, {}).get("chunk_count", 0)
        record["file_ids"] = [f for f in record.get("file_ids", []) if f != file_id]
        record.get("files", {}).pop(file_id, None)
        record["updated_at"] = time.time()
        self._store.save_state(_project_key(project_id), record)
        return chunk_count
