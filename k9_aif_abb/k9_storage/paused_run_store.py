# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
PausedRunStore (1.29.0): where an agent framework's paused run waits while a person decides.

When an agent framework pauses for approval (the OpenAI Agents SDK's ``needs_approval``, for one), its run
state is saved here under a key, and only the key travels with the HIL request: through the orchestrator's
resume payload, Kafka, K9X HIL and back. The state itself never goes into a payload that governance screens
again (it was screened as each piece entered the run) or that a reviewer sees. Large data travels as a link,
the same principle as the framework's large events.

One table, ``k9_paused_runs``: PostgreSQL in production (the schema from ``postgres.schema``, e.g. ``openai``),
SQLite when no PostgreSQL is configured. Built on the same storage backends as ``RoutingStateStore``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, delete, insert, select

log = logging.getLogger(__name__)

TABLE = "k9_paused_runs"


class PausedRunStore:
    """Save, load and discard paused runs by key."""

    def __init__(self, db: Any):
        self.db = db
        metadata: MetaData = db.metadata
        self.table = Table(
            TABLE, metadata,
            Column("run_key", String, primary_key=True),
            Column("framework", String, nullable=False),
            Column("agent", String, nullable=False),
            Column("state", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            extend_existing=True,
        )
        metadata.create_all(db.engine, tables=[self.table], checkfirst=True)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None) -> "PausedRunStore":
        """PostgreSQL when ``postgres.enabled`` is true (database and schema from ``postgres``), else SQLite at
        ``hil.paused_runs_db`` (default ``./runtime/paused_runs.db``)."""
        config = config or {}
        pg = config.get("postgres") or {}
        if pg.get("enabled"):
            from k9_aif_abb.k9_storage.postgres_database_storage import PostgresDatabaseStorage
            return cls(PostgresDatabaseStorage(config=config))
        from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage
        path = (config.get("hil") or {}).get("paused_runs_db") or "./runtime/paused_runs.db"
        return cls(SQLiteDatabaseStorage(db_path=path))

    def save(self, framework: str, agent: str, state: str) -> str:
        key = f"{framework}:{uuid.uuid4().hex}"
        with self.db.engine.begin() as conn:
            conn.execute(insert(self.table).values(run_key=key, framework=framework, agent=agent, state=state,
                                                   created_at=datetime.now(timezone.utc)))
        log.info("[PausedRunStore] saved paused run %s (agent=%s, %d chars)", key, agent, len(state))
        return key

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        with self.db.engine.begin() as conn:
            row = conn.execute(select(self.table).where(self.table.c.run_key == key)).mappings().first()
        return dict(row) if row else None

    def discard(self, key: str) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(delete(self.table).where(self.table.c.run_key == key))
