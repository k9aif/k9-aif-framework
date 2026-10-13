# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""SqlDataAdapter — built-in BaseDataAdapter for SQL databases through SQLAlchemy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base_data_adapter import BaseDataAdapter


class SqlDataAdapter(BaseDataAdapter):
    """
    Read-only SQL through SQLAlchemy: PostgreSQL, Oracle, SQL Server, MySQL, Db2, SQLite, or any
    database with a SQLAlchemy dialect (and its driver installed). Config keys: ``connection``
    (SQLAlchemy URL, from the environment), ``query`` (with ``:named`` parameters).

    Queries always run with bound parameters, never string formatting. Registered as ``sql``
    in IntegrationAdapterFactory.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._engine = None

    def _engine_for(self):
        if self._engine is None:
            from sqlalchemy import create_engine
            url = self.config.get("connection")
            if not url:
                raise ValueError("SqlDataAdapter needs config['connection'] (a SQLAlchemy URL)")
            self._engine = create_engine(url, pool_pre_ping=True)
        return self._engine

    def read(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import text
        with self._engine_for().connect() as conn:
            result = conn.execute(text(query or self.config.get("query", "")), params or {})
            return [dict(row._mapping) for row in result]
