# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Table,
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    Float,
    JSON,
    select,
    insert,
    update,
    or_,
    and_,
    text,
)

log = logging.getLogger(__name__)


class RoutingStateStore:
    """
    OOB Router State Store SBB
    --------------------------
    Provides domain-specific persistence for:
    - sessions
    - session_turns
    - routing_decisions
    - context_artifacts
    - hil_pending (paused flows awaiting a human decision -- see
      BaseHILOrchestrator / RequiresHIL)
    - routing_outcomes (what each model actually did: success, latency and,
      when graded, quality -- the evidence K9ModelRouter learns from)

    Supports both:
    - PostgreSQL (existing schema / reflection)
    - SQLite (OOB auto-created schema)
    """

    def __init__(self, db):
        self.db = db
        self._init_tables()

    # ------------------------------------------------------------------
    # Table Initialization / Reflection
    # ------------------------------------------------------------------
    def _init_tables(self):
        metadata = self.db.metadata
        engine = self.db.engine

        try:
            # Try reflection first (Postgres / pre-created schema)
            self.sessions = Table("sessions", metadata, autoload_with=engine)
            self.session_turns = Table("session_turns", metadata, autoload_with=engine)
            self.routing_decisions = Table(
                "routing_decisions", metadata, autoload_with=engine
            )
            self.context_artifacts = Table(
                "context_artifacts", metadata, autoload_with=engine
            )

        except Exception:
            # Fallback: create OOB schema (SQLite mode)

            self.sessions = Table(
                "sessions",
                metadata,
                Column("session_id", String, primary_key=True),
                Column("user_id", String, nullable=False),
                Column("status", String, default="ACTIVE"),
                Column("current_dpl_level", Integer, default=1),
                Column("model_affinity", String),
                Column("active_prefix_hash", Text),
                Column("session_summary", Text),
                Column("created_at", DateTime),
                Column("last_active", DateTime),
                Column("closed_at", DateTime),
            )

            self.session_turns = Table(
                "session_turns",
                metadata,
                Column("turn_id", Integer, primary_key=True, autoincrement=True),
                Column("session_id", String, nullable=False),
                Column("turn_index", Integer, nullable=False),
                Column("role", String, nullable=False),
                Column("content", Text, nullable=False),
                Column("token_count", Integer),
                Column("compressed_flag", Boolean, default=False),
                Column("created_at", DateTime),
            )

            self.routing_decisions = Table(
                "routing_decisions",
                metadata,
                Column("decision_id", Integer, primary_key=True, autoincrement=True),
                Column("session_id", String, nullable=False),
                Column("turn_id", Integer),
                Column("selected_model", String, nullable=False),
                Column("routing_reason", Text, nullable=False),
                Column("complexity_score", Float),
                Column("governance_score", Float),
                Column("prompt_hash", Text),
                Column("decision_metadata", JSON),
                Column("created_at", DateTime),
            )

            self.context_artifacts = Table(
                "context_artifacts",
                metadata,
                Column("artifact_id", Integer, primary_key=True, autoincrement=True),
                Column("session_id", String, nullable=False),
                Column("artifact_type", String),
                Column("content_summary", Text),
                Column("full_content_pointer", Text),
                Column("content_hash", Text),
                Column("cache_eligible", Boolean, default=True),
                Column("created_at", DateTime),
            )

            metadata.create_all(engine)

        # hil_pending is reflected/created independently of the four
        # tables above -- an existing DB that predates this table (has
        # sessions/session_turns/routing_decisions/context_artifacts
        # already, but not yet hil_pending) must not fall all the way
        # through to redefining those four from scratch just because this
        # one new table isn't there yet. Confirmed live: without this
        # isolation, partial reflection success (4 tables reflect fine,
        # hil_pending's reflection then fails) drops into the fallback
        # branch above, which tries to Table()-define sessions etc. a
        # second time against a MetaData that already has them registered
        # -> sqlalchemy.exc.InvalidRequestError.
        try:
            self.hil_pending = Table("hil_pending", metadata, autoload_with=engine)
        except Exception:
            self.hil_pending = Table(
                "hil_pending",
                metadata,
                Column("correlation_id", String, primary_key=True),
                Column("orchestrator_module", String, nullable=False),
                Column("orchestrator_class", String, nullable=False),
                Column("reply_to", String, nullable=False),
                Column("reason", Text),
                Column("priority", String, default="medium"),
                Column("payload", JSON),
                Column("status", String, default="pending"),
                Column("created_at", DateTime),
                Column("resolved_at", DateTime),
                Column("decision", JSON),
                Column("resuming_at", DateTime),
            )
            metadata.create_all(engine)
        self.hil_pending = self._add_missing_columns(
            engine, metadata, self.hil_pending, [Column("decision", JSON), Column("resuming_at", DateTime)])

        # routing_outcomes is also reflected/created on its own, for the same
        # reason as hil_pending: existing databases predate it.
        try:
            self.routing_outcomes = Table("routing_outcomes", metadata, autoload_with=engine)
        except Exception:
            self.routing_outcomes = Table(
                "routing_outcomes",
                metadata,
                Column("outcome_id", Integer, primary_key=True, autoincrement=True),
                Column("session_id", String),
                Column("task_type", String),
                Column("model_alias", String, nullable=False),
                Column("success", Boolean, default=True),
                Column("quality", Float),
                Column("latency_ms", Float),
                Column("prompt_hash", Text),
                Column("embedder", String),
                Column("prompt_vector", JSON),
                Column("source", String, default="runtime"),
                Column("created_at", DateTime),
            )
            metadata.create_all(engine)
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Indexes for the queries made on every model call (1.26.1). Without them, each call scanned the whole
        session_turns table (append_turn: latest turn of a session), so per-call cost grew with the routing
        history: measured at 44,808 rows per table, a three-agent workflow took ~135 ms instead of ~23 ms.
        Created with IF NOT EXISTS, so existing databases (SQLite or PostgreSQL, reflected or created here)
        get them on the next start. A failure (e.g. no CREATE privilege) affects speed only: logged, not raised."""
        from sqlalchemy import Index
        wanted = [
            ("ix_session_turns_session_turn", self.session_turns, ("session_id", "turn_index")),
            ("ix_routing_decisions_session", self.routing_decisions, ("session_id",)),
            ("ix_context_artifacts_session", self.context_artifacts, ("session_id",)),
            ("ix_routing_outcomes_embedder_id", self.routing_outcomes, ("embedder", "outcome_id")),
            ("ix_hil_pending_status", self.hil_pending, ("status", "resuming_at")),
        ]
        for name, table, cols in wanted:
            if not all(c in table.c for c in cols):
                continue
            idx = Index(name, *(table.c[c] for c in cols))
            try:
                idx.create(bind=self.db.engine, checkfirst=True)
            except Exception as exc:
                log.warning("[RoutingStateStore] could not create index %s (%s); routing state queries will "
                            "scan the table and slow down as it grows", name, exc)

    @staticmethod
    def _add_missing_columns(engine, metadata, table: Table, columns: List[Column]) -> Table:
        """Additive migration for a table reflected from an existing database (1.23: the
        hil_pending resume columns). Returns the table re-reflected with the new columns."""
        missing = [c for c in columns if c.name not in table.c]
        if not missing:
            return table
        qualified = f"{table.schema}.{table.name}" if table.schema else table.name
        with engine.begin() as conn:
            for col in missing:
                conn.execute(text(f"ALTER TABLE {qualified} ADD COLUMN {col.name} "
                                  f"{col.type.compile(dialect=engine.dialect)}"))
        metadata.remove(table)
        return Table(table.name, metadata, autoload_with=engine, schema=table.schema)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------
    def ensure_session(self, session_id: str, user_id: str) -> None:
        with self.db.get_session() as session:
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

            session.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_session() as session:
            stmt = select(self.sessions).where(
                self.sessions.c.session_id == session_id
            )
            row = session.execute(stmt).fetchone()
            return dict(row._mapping) if row else None

    def update_model_affinity(self, session_id: str, model_name: str) -> None:
        with self.db.get_session() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(model_affinity=model_name, last_active=datetime.utcnow())
            )
            session.commit()

    def update_prefix_hash(self, session_id: str, prefix_hash: str) -> None:
        with self.db.get_session() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(active_prefix_hash=prefix_hash)
            )
            session.commit()

    def update_session_summary(self, session_id: str, summary: str) -> None:
        with self.db.get_session() as session:
            session.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == session_id)
                .values(session_summary=summary)
            )
            session.commit()

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
        with self.db.get_session() as session:
            stmt = (
                select(self.session_turns.c.turn_index)
                .where(self.session_turns.c.session_id == session_id)
                .order_by(self.session_turns.c.turn_index.desc())
            )

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

            session.commit()

            inserted_turn_id = result.inserted_primary_key[0]
            return inserted_turn_id

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
        with self.db.get_session() as session:
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
            session.commit()

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
        with self.db.get_session() as session:
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
            session.commit()

    # ------------------------------------------------------------------
    # HIL Pending Flows -- paused workflows awaiting a human decision.
    #
    # Not just a routing-table lookup: enough is persisted here to know
    # which Orchestrator class to reconstruct and resume when the reply
    # comes back, not merely which topic to reply to. See
    # BaseHILOrchestrator.execute_flow() (writer) and
    # K9EventRouter's HIL-reply handling (reader).
    # ------------------------------------------------------------------
    def record_hil_pending(
        self,
        correlation_id: str,
        orchestrator_module: str,
        orchestrator_class: str,
        reply_to: str,
        payload: Dict[str, Any],
        reason: Optional[str] = None,
        priority: str = "medium",
    ) -> None:
        with self.db.get_session() as session:
            session.execute(
                insert(self.hil_pending).values(
                    correlation_id=correlation_id,
                    orchestrator_module=orchestrator_module,
                    orchestrator_class=orchestrator_class,
                    reply_to=reply_to,
                    reason=reason,
                    priority=priority,
                    payload=payload,
                    status="pending",
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()

    def get_hil_pending(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_session() as session:
            stmt = select(self.hil_pending).where(
                self.hil_pending.c.correlation_id == correlation_id
            )
            row = session.execute(stmt).fetchone()
            return dict(row._mapping) if row else None

    def resolve_hil_pending(self, correlation_id: str) -> bool:
        """Atomically mark a pending HIL flow resolved -- the compare-and-
        swap gate a caller MUST use to decide whether to re-route (G-16).
        Does not delete the row -- kept for audit/traceability, same
        append-don't-erase posture as the rest of this store.

        Returns True only if this call is the one that actually
        transitioned pending -> resolved (exactly one row changed).
        False means the row was already resolved -- by a genuine
        duplicate Kafka delivery, an outbox immediate-attempt/sweep race
        (see hil_reply.py), or a second Router instance racing on the
        same reply -- and the caller must NOT re-route in that case, or
        a flow that already resumed once resumes again. Guessed-safe by
        an earlier version of this method (unconditional UPDATE, no
        WHERE on status, no return value) -- confirmed wrong: get_hil_pending()
        has no status filter either, so a duplicate reply found a real
        row and re-routed regardless of whether it was already resolved.
        """
        with self.db.get_session() as session:
            result = session.execute(
                update(self.hil_pending)
                .where(
                    self.hil_pending.c.correlation_id == correlation_id,
                    self.hil_pending.c.status == "pending",
                )
                .values(status="resolved", resolved_at=datetime.utcnow())
            )
            session.commit()
            return result.rowcount == 1

    # ------------------------------------------------------------------
    # Resuming a paused flow (1.23, closes G-18). resolve_hil_pending() marked the row resolved
    # *before* the flow was re-routed, so a crash between the two lost the resume. Now:
    #   pending --begin_hil_resume (CAS, stores the decision)--> resuming
    #   --route() succeeds--> finish_hil_resume --> resolved
    #   route() fails --> release_hil_resume --> pending (the reply is delivered again)
    #   crash while resuming --> stalled_hil_resumes() after the lease --> the Router's
    #   recovery sweep re-routes with the stored decision.
    # ------------------------------------------------------------------
    def begin_hil_resume(self, correlation_id: str, decision: Dict[str, Any],
                         lease_seconds: float = 300.0) -> bool:
        """Claim a paused flow for resuming and store the decision. True only for the caller
        that made the transition: from ``pending``, or from a ``resuming`` claim whose lease
        expired (a Router that crashed mid-resume). A duplicate reply, or a second Router while
        the claim is live, gets False and must not re-route."""
        now = datetime.utcnow()
        expired = now - timedelta(seconds=lease_seconds)
        hp = self.hil_pending.c
        with self.db.get_session() as session:
            result = session.execute(
                update(self.hil_pending)
                .where(hp.correlation_id == correlation_id,
                       or_(hp.status == "pending",
                           and_(hp.status == "resuming", hp.resuming_at < expired)))
                .values(status="resuming", decision=decision, resuming_at=now)
            )
            session.commit()
            return result.rowcount == 1

    def finish_hil_resume(self, correlation_id: str) -> None:
        """The resumed flow was re-routed: resuming -> resolved."""
        hp = self.hil_pending.c
        with self.db.get_session() as session:
            session.execute(
                update(self.hil_pending)
                .where(hp.correlation_id == correlation_id, hp.status == "resuming")
                .values(status="resolved", resolved_at=datetime.utcnow())
            )
            session.commit()

    def release_hil_resume(self, correlation_id: str) -> None:
        """Re-routing failed: back to pending, so the redelivered reply can claim it again."""
        hp = self.hil_pending.c
        with self.db.get_session() as session:
            session.execute(
                update(self.hil_pending)
                .where(hp.correlation_id == correlation_id, hp.status == "resuming")
                .values(status="pending", resuming_at=None)
            )
            session.commit()

    def stalled_hil_resumes(self, lease_seconds: float = 300.0) -> List[Dict[str, Any]]:
        """Flows claimed for resuming whose lease expired: the Router that claimed them stopped
        before finishing. Each carries the stored decision."""
        hp = self.hil_pending.c
        expired = datetime.utcnow() - timedelta(seconds=lease_seconds)
        with self.db.get_session() as session:
            rows = session.execute(
                select(self.hil_pending).where(hp.status == "resuming", hp.resuming_at < expired)
            ).fetchall()
            return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Routing Outcomes -- the evidence the learned router trains on.
    # Runtime rows (every routed call) carry success + latency; graded rows
    # (record_feedback, K9X Arena, evaluators) also carry quality 0-100 and
    # the prompt vector used for similarity.
    # ------------------------------------------------------------------
    def record_outcome(
        self,
        model_alias: str,
        task_type: Optional[str] = None,
        success: bool = True,
        quality: Optional[float] = None,
        latency_ms: Optional[float] = None,
        session_id: Optional[str] = None,
        prompt_hash: Optional[str] = None,
        embedder: Optional[str] = None,
        prompt_vector: Any = None,
        source: str = "runtime",
    ) -> None:
        if isinstance(prompt_vector, dict):
            # JSON object keys must be strings.
            prompt_vector = {str(k): v for k, v in prompt_vector.items()}
        with self.db.get_session() as session:
            session.execute(
                insert(self.routing_outcomes).values(
                    session_id=session_id,
                    task_type=task_type,
                    model_alias=model_alias,
                    success=success,
                    quality=quality,
                    latency_ms=latency_ms,
                    prompt_hash=prompt_hash,
                    embedder=embedder,
                    prompt_vector=prompt_vector,
                    source=source,
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()

    def load_outcomes(
        self,
        graded_only: bool = False,
        embedder: Optional[str] = None,
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Newest first. ``graded_only`` returns rows with a quality score
        (and, with ``embedder``, only vectors from that embedder)."""
        t = self.routing_outcomes
        stmt = select(t)
        if graded_only:
            stmt = stmt.where(t.c.quality.isnot(None))
        if embedder:
            stmt = stmt.where(t.c.embedder == embedder)
        stmt = stmt.order_by(t.c.outcome_id.desc()).limit(limit)
        with self.db.get_session() as session:
            rows = [dict(r._mapping) for r in session.execute(stmt).fetchall()]
        for row in rows:
            vec = row.get("prompt_vector")
            if isinstance(vec, dict):
                row["prompt_vector"] = {int(k): float(v) for k, v in vec.items()}
        return rows
