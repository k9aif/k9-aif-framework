# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Table, select, insert, update
from sqlalchemy.orm import Session

from k9_aif_abb.k9_storage.postgres_database_storage import PostgresDatabaseStorage


class RoutingStateStore:
    """
    OOB Router State Store SBB
    --------------------------
    Provides domain-specific persistence for:
    - sessions
    - session_turns
    - routing_decisions
    - context_artifacts

    Uses PostgresDatabaseStorage underneath.
    """

    def __init__(self, db: PostgresDatabaseStorage):
        self.db = db
        self._init_tables()

    # ------------------------------------------------------------------
    # Table Reflection
    # ------------------------------------------------------------------
    def _init_tables(self):
        metadata = self.db.metadata
        engine = self.db.engine

        self.sessions = Table("sessions", metadata, autoload_with=engine)
        self.session_turns = Table("session_turns", metadata, autoload_with=engine)
        self.routing_decisions = Table("routing_decisions", metadata, autoload_with=engine)
        self.context_artifacts = Table("context_artifacts", metadata, autoload_with=engine)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------
    def ensure_session(self, session_id: str, user_id: str) -> None:
        with self.db.begin() as session:
            stmt = select(self.sessions.c.session_id).where(
                self.sessions.c.session_id == session_id
            )
            exists = session.execute(stmt).fetchone()

            if not exists:
                session.execute(
                    insert(self.sessions).values(
                        session_id=session_id,
                        user_id=user_id,
                        created_at=datetime.utcnow(),
                        last_active=datetime.utcnow(),
                        status="ACTIVE",
                    )
                )
            else:
                session.execute(
                    update(self.sessions)
                    .where(self.sessions.c.session_id == session_id)
                    .values(last_active=datetime.utcnow())
                )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.db.begin() as session:
            stmt = select(self.sessions).where(
                self.sessions.c.session_id == session_id
            )
            row = session.execute(stmt).fetchone()
            return dict(row._mapping) if row else None

    def update_model_affinity(self, session_id: str, model_name: str) -> None:
        with self.db.begin() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(model_affinity=model_name, last_active=datetime.utcnow())
            )

    def update_prefix_hash(self, session_id: str, prefix_hash: str) -> None:
        with self.db.begin() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(active_prefix_hash=prefix_hash)
            )

    def update_session_summary(self, session_id: str, summary: str) -> None:
        with self.db.begin() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(session_summary=summary)
            )

    # ------------------------------------------------------------------
    # Session Turns
    # ------------------------------------------------------------------
    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: Optional[int] = None,
        compressed_flag: bool = False,
    ) -> int:
        with self.db.begin() as session:
            # Get next turn index
            stmt = select(self.session_turns.c.turn_index).where(
                self.session_turns.c.session_id == session_id
            ).order_by(self.session_turns.c.turn_index.desc())

            last = session.execute(stmt).fetchone()
            next_index = (last[0] + 1) if last else 1

            result = session.execute(
                insert(self.session_turns).values(
                    session_id=session_id,
                    turn_index=next_index,
                    role=role,
                    content=content,
                    token_count=token_count,
                    compressed_flag=compressed_flag,
                    created_at=datetime.utcnow(),
                )
            )

            return next_index

    # ------------------------------------------------------------------
    # Routing Decisions
    # ------------------------------------------------------------------
    def record_routing_decision(
        self,
        session_id: str,
        turn_id: Optional[int],
        selected_model: str,
        routing_reason: str,
        complexity_score: Optional[float] = None,
        governance_score: Optional[float] = None,
        prompt_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.db.begin() as session:
            session.execute(
                insert(self.routing_decisions).values(
                    session_id=session_id,
                    turn_id=turn_id,
                    selected_model=selected_model,
                    routing_reason=routing_reason,
                    complexity_score=complexity_score,
                    governance_score=governance_score,
                    prompt_hash=prompt_hash,
                    decision_metadata=metadata,
                    created_at=datetime.utcnow(),
                )
            )

    # ------------------------------------------------------------------
    # Context Artifacts (Shadow Context)
    # ------------------------------------------------------------------
    def store_context_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content_summary: Optional[str] = None,
        full_content_pointer: Optional[str] = None,
        content_hash: Optional[str] = None,
        cache_eligible: bool = True,
    ) -> None:
        with self.db.begin() as session:
            session.execute(
                insert(self.context_artifacts).values(
                    session_id=session_id,
                    artifact_type=artifact_type,
                    content_summary=content_summary,
                    full_content_pointer=full_content_pointer,
                    content_hash=content_hash,
                    cache_eligible=cache_eligible,
                    created_at=datetime.utcnow(),
                )
            )