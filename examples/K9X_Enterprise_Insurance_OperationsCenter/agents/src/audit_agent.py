# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_audit_agent (SBB)
#
# Responsibilities:
#   - Construct immutable AuditEntry records for every agent action
#   - Persist to eoc.audit_entries table in PostgreSQL
#   - Support audit query retrieval for compliance reports
#   - Never modify or delete existing audit records

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent

_TABLE = "eoc.audit_entries"


class AuditAgent(BaseAgent):
    """
    SBB: k9_sbb_audit_agent

    Immutable audit record construction and compliance report generation.
    Persists AuditEntry records to PostgreSQL (eoc.audit_entries).
    Does not invoke an LLM.
    """

    layer = "EOC Audit SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self._pg_cfg = self._resolve_pg_cfg()
        self.logger.info(
            f"[{self.layer}] PostgreSQL audit: "
            f"{self._pg_cfg['host']}:{self._pg_cfg['port']}/{self._pg_cfg['database']}"
        )

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        mode = payload.get("audit_mode", "write")
        if mode == "query":
            return self._query_audit(payload)
        return self._write_audit(payload)

    # ------------------------------------------------------------------
    def _write_audit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        audit_id       = f"AUD-{uuid.uuid4().hex[:12].upper()}"
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        timestamp      = datetime.now(timezone.utc).isoformat()

        prompt_text   = payload.get("prompt_text", "")
        response_text = payload.get("response_text", "")
        prompt_hash   = hashlib.sha256(prompt_text.encode()).hexdigest() if prompt_text else None
        response_hash = hashlib.sha256(response_text.encode()).hexdigest() if response_text else None

        entry = {
            "audit_id":         audit_id,
            "event_id":         payload.get("event_id", ""),
            "event_type":       payload.get("event_type", ""),
            "squad_id":         payload.get("squad_id", ""),
            "agent_name":       payload.get("source_agent", payload.get("agent", "")),
            "model_id":         payload.get("model_id", ""),
            "model_provider":   payload.get("model_provider", ""),
            "model_version":    payload.get("model_version", ""),
            "prompt_hash":      prompt_hash,
            "response_hash":    response_hash,
            "confidence_score": self._resolve_confidence(payload),
            "disposition":      self._resolve_disposition(payload),
            "governance_checks": json.dumps(self._resolve_governance_checks(payload)),
            "timestamp_utc":    timestamp,
            "session_id":       payload.get("session_id"),
            "correlation_id":   correlation_id,
            "operator_id":      payload.get("operator_id"),
        }

        self._persist_entry(entry)

        self.publish_event({
            "type":         "AuditEntryWritten",
            "audit_id":     audit_id,
            "correlation_id": correlation_id,
            "agent_name":   entry["agent_name"],
            "event_type":   entry["event_type"],
        })

        self.logger.info(
            f"[{self.layer}] AuditEntry written: {audit_id} "
            f"agent={entry['agent_name']} event={entry['event_type']}"
        )

        return {
            "agent":          "AuditAgent",
            "audit_id":       audit_id,
            "correlation_id": correlation_id,
            "status":         "written",
            "timestamp_utc":  timestamp,
        }

    # ------------------------------------------------------------------
    def _query_audit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        filters = {
            k: payload[k]
            for k in ("correlation_id", "event_id", "agent_name", "event_type")
            if payload.get(k)
        }
        limit   = int(payload.get("limit", 100))
        entries = self._fetch_entries(filters, limit)

        self.logger.info(
            f"[{self.layer}] Audit query: {len(entries)} entries filters={list(filters.keys())}"
        )

        return {
            "agent":      "AuditAgent",
            "audit_mode": "query",
            "filters":    filters,
            "count":      len(entries),
            "entries":    entries,
        }

    # ------------------------------------------------------------------
    def _resolve_confidence(self, payload: Dict[str, Any]) -> float:
        if "confidence" in payload:
            return float(payload["confidence"])
        for key in ("adjudication", "triage", "intent", "fraud_assessment", "impact_assessment"):
            nested = payload.get(key, {})
            if isinstance(nested, dict) and "confidence" in nested:
                return float(nested["confidence"])
        return 0.0

    def _resolve_disposition(self, payload: Dict[str, Any]) -> str:
        for key in ("decision", "disposition"):
            if key in payload:
                return str(payload[key])
        for result_key in ("adjudication", "triage", "fraud_assessment", "impact_assessment"):
            nested = payload.get(result_key, {})
            if isinstance(nested, dict):
                for key in ("decision", "recommendation"):
                    if key in nested:
                        return str(nested[key])
        return ""

    def _resolve_governance_checks(self, payload: Dict[str, Any]) -> dict:
        if "governance_checks" in payload:
            return payload["governance_checks"]
        guard = payload.get("guard", {})
        return {
            "guard_passed": guard.get("passed"),
            "pii_detected": guard.get("pii_detected"),
            "violations":   guard.get("policy_violations", []),
        }

    # ------------------------------------------------------------------
    def _resolve_pg_cfg(self) -> Dict[str, Any]:
        pg = self.config.get("postgres", {})
        return {
            "host":     os.getenv("K9_PG_HOST")     or pg.get("host",     "localhost"),
            "port":     int(os.getenv("K9_PG_PORT") or pg.get("port",     5432)),
            "database": os.getenv("K9_PG_DB")       or pg.get("database", "eoc"),
            "user":     os.getenv("K9_PG_USER")     or pg.get("user",     "postgres"),
            "password": os.getenv("K9_PG_PASSWORD") or pg.get("password", ""),
            "options":  f"-c search_path={pg.get('schema', 'eoc')}",
        }

    def _connect(self):
        return psycopg2.connect(**self._pg_cfg)

    def _persist_entry(self, entry: Dict[str, Any]):
        cols         = ", ".join(entry.keys())
        placeholders = ", ".join(["%s"] * len(entry))
        sql = (
            f"INSERT INTO {_TABLE} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT (audit_id) DO NOTHING"
        )
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, list(entry.values()))
        except Exception as exc:
            self.logger.error(f"[{self.layer}] Failed to persist audit entry: {exc}")

    def _fetch_entries(self, filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        where_sql = " AND ".join(f"{k} = %s" for k in filters) if filters else "TRUE"
        sql = (
            f"SELECT * FROM {_TABLE} WHERE {where_sql} "
            f"ORDER BY timestamp_utc DESC LIMIT %s"
        )
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, list(filters.values()) + [limit])
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            self.logger.error(f"[{self.layer}] Failed to fetch audit entries: {exc}")
            return []
