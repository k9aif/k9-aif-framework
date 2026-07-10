# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseDataAdapter — ABB for direct data store connectors
(PostgreSQL, MySQL, S3, Redshift, Snowflake, BigQuery, MongoDB).

Distinct from k9_storage (object storage for documents) — this adapter is for
structured data queries and writes within a business process flow.

Concrete SBBs implement read() and/or write(); execute() is the fixed template.
Config keys: connection, schema, table, operation (read | write | both).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List, Optional

from .base_integration_adapter import BaseIntegrationAdapter


class BaseDataAdapter(BaseIntegrationAdapter):
    """ABB for deterministic data store read/write — no LLM inference."""

    @abstractmethod
    def read(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a read operation. Return list of result records."""

    def write(self, data: Dict[str, Any], target: Optional[str] = None) -> Any:
        """Execute a write operation. Override when writes are needed."""
        raise NotImplementedError(f"{self.adapter_name} does not implement write()")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        operation = self.config.get("operation", payload.get("operation", "read"))
        try:
            if operation == "write":
                result = self.write(payload, self.config.get("table"))
                return {"adapter": self.adapter_name, "status": "success", "operation": "write", "result": result}
            query  = payload.get("query", self.config.get("query", ""))
            params = payload.get("params")
            rows   = self.read(query, params)
            return {"adapter": self.adapter_name, "status": "success", "operation": "read", "rows": rows, "count": len(rows)}
        except Exception as exc:
            return self.handle_error(exc, payload)
