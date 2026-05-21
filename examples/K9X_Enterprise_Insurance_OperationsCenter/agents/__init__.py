# SPDX-License-Identifier: Apache-2.0

"""
K9-AIF EOC — SBB Agents Package
=================================

This package contains all **Solution Building Block (SBB) agents** for the
K9-AIF Enterprise Insurance Operations Center (EOC).

Each agent is a concrete implementation that extends the K9-AIF
``BaseAgent`` ABB and implements the ``execute(payload)`` contract.

Agents
------

ClaimsTriageAgent (claims_triage_agent)
    Triages incoming claims: completeness check, coverage match, and
    priority scoring (critical / high / normal / low).
    Uses K9ModelRouter (EOCModelRouter) for LLM-assisted reasoning.
    Emits ``ClaimsTriageCompleted`` event on the bus.

AdjudicationAgent (adjudication_agent)
    Policy coverage reasoning and liability determination.
    Produces approve / deny / partial / escalate decisions with
    confidence scores. Routes to the ``reasoning`` model capability
    (Granite 3.x via EOCModelRouter).
    Emits ``AdjudicationCompleted`` event.

GuardAgent (guard_agent)
    Pre/post-inference governance layer.
    Applies regex-based PII pattern scanning *and* AI-powered
    Granite Guardian compliance checks. Hard-routes to the ``guardrails``
    capability — no fallback model accepted.
    Emits ``GuardCheckCompleted`` event.

EscalationAgent (escalation_agent)
    Confidence-threshold enforcement and HITL queue packaging.
    Raises an ``EscalationTicket`` when confidence < threshold or
    the guard check fails. Purely deterministic — no LLM invoked.
    Emits ``EscalationRaised`` event.

AuditAgent (audit_agent)
    Immutable audit record writer and query engine.
    Persists ``AuditEntry`` rows to SQLite (dev) or PostgreSQL (prod).
    Supports write mode (default) and query mode
    (``audit_mode='query'``). Never modifies or deletes existing records.
    Emits ``AuditEntryWritten`` event.

DocumentExtractorAgent (document_extractor_agent)
    OCR pipeline: file ingestion → Tesseract text extraction →
    LLM-structured output → schema validation.
    Routes to the ``extraction`` capability (Granite Code).
    Emits ``DocumentExtractionCompleted`` event.

FraudDetectionAgent (fraud_detection_agent)
    Risk signal correlation, watchlist keyword matching, and anomaly
    flagging. Produces a risk score (0.0–1.0) and recommendation
    (monitor / flag / block / escalate).
    Routes to ``reasoning`` capability (Granite 3.x).
    Emits ``FraudAssessmentCompleted`` event.

GraphSyncAgent (graph_sync_agent)
    Translates agent outputs into Neo4j node and relationship updates.
    Gracefully degrades when Neo4j is unavailable
    (``eoc.graph_sync_enabled: false`` in config).
    Emits ``GraphSyncCompleted`` event.

Common Payload Contract
-----------------------
All agents accept a ``payload: dict`` and return a ``result: dict``.
Every result includes at minimum::

    {
        "agent":          str,   # agent class name
        "correlation_id": str,   # trace identifier across squads
        "timestamp_utc":  str,   # ISO-8601 UTC timestamp
    }

Framework Integration
---------------------
Agents plug into the K9-AIF framework via:

- ``BaseAgent`` — lifecycle, governance hooks, monitor, message bus
- ``ModelRouterFactory.get_router(config)`` — LLM routing via EOCModelRouter
- ``InferenceRequest`` — typed LLM request with task_type and sensitivity
- ``publish_event(event)`` — puts events on the K9EventBus (Redpanda)

Example Usage
-------------
::

    from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.claims_triage_agent import ClaimsTriageAgent
    from k9_aif_abb.k9_utils.config_loader import load_yaml

    config = load_yaml("examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml")
    agent = ClaimsTriageAgent(config=config)

    result = agent.execute({
        "claim_id": "CLM-001",
        "claimant_id": "C-100",
        "policy_id": "POL-500",
        "claim_type": "property_damage",
        "amount_claimed": 45000.00,
        "notes": "Water damage from burst pipe",
        "correlation_id": "eoc-trace-abc123",
    })
    print(result["priority"], result["confidence"])
"""

# Re-export all agents from src for convenient top-level imports.
# Both of these are equivalent:
#   from examples.K9X_Enterprise_Insurance_OperationsCenter.agents import ClaimsTriageAgent
#   from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src import ClaimsTriageAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src import (
    ClaimsTriageAgent,
    AdjudicationAgent,
    GuardAgent,
    EscalationAgent,
    AuditAgent,
    DocumentExtractorAgent,
    FraudDetectionAgent,
    GraphSyncAgent,
)

__all__ = [
    "ClaimsTriageAgent",
    "AdjudicationAgent",
    "GuardAgent",
    "EscalationAgent",
    "AuditAgent",
    "DocumentExtractorAgent",
    "FraudDetectionAgent",
    "GraphSyncAgent",
]

