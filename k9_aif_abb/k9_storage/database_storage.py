# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary

from typing import Any, Dict, Optional
import threading


class BaseDatabaseStorage:
    """Base DB storage with in-memory dict fallback."""

    def __init__(self):
        self._tables: Dict[str, list[Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def insert(self, table: str, record: Dict[str, Any]) -> None:
        with self._lock:
            self._tables.setdefault(table, []).append(record)

    def query(self, table: str, filters: Dict[str, Any]) -> list[Dict[str, Any]]:
        rows = self._tables.get(table, [])
        return [row for row in rows if all(row.get(k) == v for k, v in filters.items())]

    def update(self, table: str, filters: Dict[str, Any], updates: Dict[str, Any]) -> None:
        with self._lock:
            for row in self._tables.get(table, []):
                if all(row.get(k) == v for k, v in filters.items()):
                    row.update(updates)

    def delete(self, table: str, filters: Dict[str, Any]) -> None:
        with self._lock:
            self._tables[table] = [
                row for row in self._tables.get(table, [])
                if not all(row.get(k) == v for k, v in filters.items())
            ]