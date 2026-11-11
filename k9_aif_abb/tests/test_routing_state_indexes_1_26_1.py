# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.26.1: the routing state tables are indexed for the queries made on every model call, so per-call cost does not
grow with history. Before, append_turn() scanned session_turns in full (measured: ~135 ms per three-agent workflow
at 44,808 rows, ~23 ms on an empty store)."""
import sqlite3

from sqlalchemy import select

from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage


def _plan(db_path, sql, params=()):
    con = sqlite3.connect(db_path)
    try:
        return " ".join(str(r[-1]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, params))
    finally:
        con.close()


def test_indexes_exist_on_a_new_store(tmp_path):
    db = tmp_path / "r.db"
    RoutingStateStore(db=SQLiteDatabaseStorage(db_path=str(db)))
    names = {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master where type='index'")}
    assert {"ix_session_turns_session_turn", "ix_routing_decisions_session", "ix_routing_outcomes_embedder_id",
            "ix_context_artifacts_session", "ix_hil_pending_status"} <= names


def test_latest_turn_lookup_uses_the_index(tmp_path):
    db = tmp_path / "r.db"
    RoutingStateStore(db=SQLiteDatabaseStorage(db_path=str(db)))
    plan = _plan(str(db), "SELECT turn_index FROM session_turns WHERE session_id = ? ORDER BY turn_index DESC LIMIT 1", ("s",))
    assert "ix_session_turns_session_turn" in plan and "SCAN session_turns" not in plan


def test_existing_database_gets_the_indexes_on_next_start(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)                 # a store created before 1.26.1: same tables, no indexes
    con.execute("CREATE TABLE session_turns (turn_id INTEGER PRIMARY KEY, session_id VARCHAR NOT NULL, "
                "turn_index INTEGER NOT NULL, role VARCHAR NOT NULL, content TEXT NOT NULL, token_count INTEGER, "
                "compressed_flag BOOLEAN, created_at DATETIME)")
    con.commit(); con.close()
    store = RoutingStateStore(db=SQLiteDatabaseStorage(db_path=str(db)))
    names = {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master where type='index'")}
    assert "ix_session_turns_session_turn" in names
    store.append_turn("s1", "user", "hello") if hasattr(store, "append_turn") else None
