# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — k9_sbb_graph_sync_agent (SBB)
#
# Responsibilities:
#   - Translate agent outputs into Neo4j node and relationship updates
#   - Create/update entity nodes (Claimant, Policy, Claim, Document)
#   - Create typed edges between entities
#   - Fail gracefully when Neo4j is unavailable (graph_sync_enabled: false)

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class GraphSyncAgent(BaseAgent):
    """
    SBB: k9_sbb_graph_sync_agent

    Translates agent outputs into Neo4j relationship and node updates.
    Gracefully degrades when Neo4j is unavailable (configured via eoc.graph_sync_enabled).
    """

    layer = "EOC GraphSync SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        eoc_cfg = self.config.get("eoc", {})
        self._graph_enabled = bool(eoc_cfg.get("graph_sync_enabled", False))
        self._driver = None

        if self._graph_enabled:
            self._driver = self._connect_neo4j()

        self.logger.info(f"[{self.layer}] GraphSync enabled={self._graph_enabled}")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
        event_type = payload.get("event_type", "unknown")

        if not self._graph_enabled or not self._driver:
            self.logger.info(f"[{self.layer}] Graph sync skipped (disabled or Neo4j unavailable)")
            return {
                "agent": "GraphSyncAgent",
                "correlation_id": correlation_id,
                "status": "skipped",
                "reason": "graph_sync_enabled=false or Neo4j unavailable",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }

        operations = self._build_operations(payload, event_type)
        results = self._execute_operations(operations)

        self.publish_event({
            "type": "GraphSyncCompleted",
            "correlation_id": correlation_id,
            "operations_count": len(operations),
        })

        self.logger.info(
            f"[{self.layer}] Graph sync: {len(operations)} ops for event_type={event_type}"
        )

        return {
            "agent": "GraphSyncAgent",
            "correlation_id": correlation_id,
            "status": "synced",
            "operations": operations,
            "results": results,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    def _build_operations(self, payload: Dict[str, Any], event_type: str) -> List[Dict[str, Any]]:
        ops = []

        if event_type in ("claim_submitted", "claim_updated"):
            if payload.get("claimant_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Claimant",
                    "key": "claimant_id",
                    "value": payload["claimant_id"],
                })
            if payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Claim",
                    "key": "claim_id",
                    "value": payload["claim_id"],
                    "properties": {
                        "claim_type": payload.get("claim_type"),
                        "status": payload.get("status", "submitted"),
                        "amount": payload.get("amount_claimed", 0),
                    },
                })
            if payload.get("claimant_id") and payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_RELATIONSHIP",
                    "from_label": "Claimant",
                    "from_key": payload["claimant_id"],
                    "to_label": "Claim",
                    "to_key": payload["claim_id"],
                    "rel_type": "FILED",
                })
            if payload.get("policy_id") and payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Policy",
                    "key": "policy_id",
                    "value": payload["policy_id"],
                })
                ops.append({
                    "type": "MERGE_RELATIONSHIP",
                    "from_label": "Claim",
                    "from_key": payload["claim_id"],
                    "to_label": "Policy",
                    "to_key": payload["policy_id"],
                    "rel_type": "COVERED_BY",
                })

        elif event_type in ("fraud_signal", "fraud_signal_raised"):
            if payload.get("claimant_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Claimant",
                    "key": "claimant_id",
                    "value": payload["claimant_id"],
                })
            if payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Claim",
                    "key": "claim_id",
                    "value": payload["claim_id"],
                    "properties": {
                        "fraud_risk_score": payload.get("risk_score", 0.0),
                        "status": "fraud_review",
                    },
                })
            if payload.get("claimant_id") and payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_RELATIONSHIP",
                    "from_label": "Claimant",
                    "from_key": payload["claimant_id"],
                    "to_label": "Claim",
                    "to_key": payload["claim_id"],
                    "rel_type": "FILED",
                })
            if payload.get("policy_id") and payload.get("claim_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Policy",
                    "key": "policy_id",
                    "value": payload["policy_id"],
                })
                ops.append({
                    "type": "MERGE_RELATIONSHIP",
                    "from_label": "Claim",
                    "from_key": payload["claim_id"],
                    "to_label": "Policy",
                    "to_key": payload["policy_id"],
                    "rel_type": "COVERED_BY",
                })

        elif event_type == "document_received":
            if payload.get("document_id"):
                ops.append({
                    "type": "MERGE_NODE",
                    "label": "Document",
                    "key": "document_id",
                    "value": payload["document_id"],
                    "properties": {"classification": payload.get("classification", "unknown")},
                })
            if payload.get("claim_id") and payload.get("document_id"):
                ops.append({
                    "type": "MERGE_RELATIONSHIP",
                    "from_label": "Claim",
                    "from_key": payload["claim_id"],
                    "to_label": "Document",
                    "to_key": payload["document_id"],
                    "rel_type": "HAS_DOCUMENT",
                })

        return ops

    def _execute_operations(self, operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._driver:
            return []
        results = []
        try:
            with self._driver.session() as session:
                for op in operations:
                    result = self._run_operation(session, op)
                    results.append(result)
        except Exception as exc:
            self.logger.error(f"[{self.layer}] Neo4j execution failed: {exc}")
        return results

    def _run_operation(self, session, op: Dict[str, Any]) -> Dict[str, Any]:
        op_type = op.get("type")
        try:
            if op_type == "MERGE_NODE":
                query = (
                    f"MERGE (n:{op['label']} {{{op['key']}: $value}}) "
                    f"ON CREATE SET n += $props "
                    f"ON MATCH SET n += $props "
                    f"RETURN n"
                )
                session.run(query, value=op["value"], props=op.get("properties", {}))
                return {"op": op_type, "label": op["label"], "status": "ok"}

            elif op_type == "MERGE_RELATIONSHIP":
                query = (
                    f"MATCH (a:{op['from_label']} {{{op['from_label'].lower()}_id: $from_key}}) "
                    f"MATCH (b:{op['to_label']} {{{op['to_label'].lower()}_id: $to_key}}) "
                    f"MERGE (a)-[r:{op['rel_type']}]->(b) "
                    f"RETURN r"
                )
                session.run(query, from_key=op["from_key"], to_key=op["to_key"])
                return {"op": op_type, "rel": op["rel_type"], "status": "ok"}

        except Exception as exc:
            return {"op": op_type, "status": "error", "error": str(exc)}

        return {"op": op_type, "status": "unknown"}

    def _connect_neo4j(self):
        import os
        try:
            from neo4j import GraphDatabase
            neo4j_cfg = self.config.get("neo4j", {})
            uri = os.getenv("NEO4J_URI") or neo4j_cfg.get("uri", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER") or neo4j_cfg.get("user", "neo4j")
            password = os.getenv("NEO4J_PASSWORD") or neo4j_cfg.get("password", "")
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            self.logger.info(f"[{self.layer}] Neo4j connected at {uri}")
            return driver
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] Neo4j connection failed: {exc}")
            return None
