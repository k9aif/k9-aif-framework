# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: examples/acme_health_insurance/agents/persistence_agent.py

import sqlite3
from typing import Dict, Any

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.persistence_factory import PersistenceFactory


class PersistenceAgent(BaseAgent):
    """
    ABB/SBB Bridge Agent
    --------------------
    Provides CRUD operations using the static PersistenceFactory
    (singleton backend). Used by all ACME Health Insurance agents.
    """

    layer = "Persistence SBB"
    _backend = None
    _logged_once = False

    def __init__(self, config: Dict[str, Any] | None = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

        # Bootstrap the PersistenceFactory (idempotent)
        PersistenceFactory.bootstrap()

        # Reuse shared backend instance
        if not PersistenceAgent._backend:
            persistence_cfg = self.config.get("persistence", {})
            backend_name = persistence_cfg.get("backend", "sqlite").lower()

            PersistenceAgent._backend = PersistenceFactory.get(
                backend_name, **persistence_cfg
            )

        backend = PersistenceAgent._backend
        self.db_path = getattr(backend, "db_path", "SBB_acme_health_insurance.db")

        # Log once per runtime
        if not PersistenceAgent._logged_once:
            self.logger.info(
                f"[{self.layer}] Using {backend.__class__.__name__} - {self.db_path}"
            )
            PersistenceAgent._logged_once = True

    # -------------------------------------------------------------------
    # Unified ABB interface
    # -------------------------------------------------------------------
    def execute(self, payload: dict) -> dict:
        action = payload.get("action")
        table = payload.get("table")
        data = payload.get("data")

        if not (action and table):
            self.logger.error(f"[{self.layer}] Missing action or table in payload")
            return {"status": "failed", "error": "Missing action or table"}

        try:
            if action == "insert":
                return self.insert(table, data)
            if action == "select":
                return self.select(table, payload.get("criteria", {}))
            if action == "update":
                return self.update(table, data, payload.get("criteria", {}))
            if action == "delete":
                return self.delete(table, payload.get("criteria", {}))
            raise ValueError(f"Unknown persistence action: {action}")
        except Exception as e:
            self.logger.error(f"[{self.layer}] Database operation failed: {e}")
            return {"status": "failed", "error": str(e)}

    # -------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------
    def insert(self, table: str, data: dict) -> dict:
        keys = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = tuple(data.values())

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(f"INSERT INTO {table} ({keys}) VALUES ({placeholders})", values)
            conn.commit()
            row_id = cur.lastrowid

        self.logger.info(f"[{self.layer}] Inserted row {row_id} into {table}")
        return {"status": "success", "row_id": row_id}

    def select(self, table: str, criteria: dict) -> dict:
        where = " AND ".join(f"{k}=?" for k in criteria) if criteria else "1=1"
        values = tuple(criteria.values())

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table} WHERE {where}", values)
            rows = cur.fetchall()

        self.logger.info(f"[{self.layer}] Selected {len(rows)} rows from {table}")
        return {"status": "success", "rows": rows}

    def update(self, table: str, data: dict, criteria: dict) -> dict:
        set_clause = ", ".join(f"{k}=?" for k in data)
        where = " AND ".join(f"{k}=?" for k in criteria) if criteria else "1=1"
        values = tuple(data.values()) + tuple(criteria.values())

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE {table} SET {set_clause} WHERE {where}", values)
            conn.commit()

        self.logger.info(f"[{self.layer}] Updated {table} with criteria={criteria}")
        return {"status": "success"}

    def delete(self, table: str, criteria: dict) -> dict:
        where = " AND ".join(f"{k}=?" for k in criteria) if criteria else "1=1"
        values = tuple(criteria.values())

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {table} WHERE {where}", values)
            conn.commit()

        self.logger.info(f"[{self.layer}] Deleted from {table} where {criteria}")
        return {"status": "success"}
