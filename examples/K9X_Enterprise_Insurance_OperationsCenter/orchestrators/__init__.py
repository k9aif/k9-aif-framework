# SPDX-License-Identifier: Apache-2.0

"""
K9-AIF EOC — Orchestrators Package
=====================================

This package contains all **SBB Orchestrators** for the K9-AIF Enterprise
Insurance Operations Center. Each orchestrator extends the K9-AIF
``BaseOrchestrator`` ABB and implements ``execute_flow(payload)``.

Architecture
------------
The EOC follows a two-level orchestration hierarchy:

1. **EOCOrchestrator** (root) — receives all enterprise events, maps
   ``event_type`` / ``intent`` to the correct squad orchestrator, and
   delegates via the registry in ``config/orchestrators.yaml``.

2. **Squad orchestrators** — each squad owns a single event type and
   drives its agent pipeline sequentially, collecting results and
   publishing the final composite outcome.

Orchestrators
-------------

EOCOrchestrator (eoc_orchestrator)
    Root orchestrator. Config-driven delegation via
    ``config/orchestrators.yaml``. Intent-to-orchestrator routing.

ClaimsProcessingOrchestrator (claims_processing_orchestrator)
    Handles ``claim_submitted`` events.
    Pipeline: ClaimsTriageAgent → AdjudicationAgent → GuardAgent →
    AuditAgent → EscalationAgent (conditional).
    Squad: ``ClaimsProcessingSquad``.

DocumentIntelligenceOrchestrator (document_intelligence_orchestrator)
    Handles ``document_received`` events.
    Pipeline: DocumentExtractorAgent → GuardAgent → GraphSyncAgent →
    AuditAgent.
    Squad: ``DocumentIntelligenceSquad``.

RiskAssessmentOrchestrator (risk_assessment_orchestrator)
    Handles ``fraud_signal_raised`` events.
    Pipeline: FraudDetectionAgent → GuardAgent → AuditAgent →
    EscalationAgent (risk_score >= 0.8).
    Squad: ``RiskAssessmentSquad``.

PolicyManagementOrchestrator (policy_management_orchestrator)
    Handles ``policy_change_requested`` events.
    Pipeline: GuardAgent → AuditAgent.
    Squad: ``PolicyManagementSquad``.

CatastropheResponseOrchestrator (catastrophe_response_orchestrator)
    Handles ``catastrophe_alert_issued`` events.
    Pipeline: FraudDetectionAgent (exposure assessment) → AuditAgent.
    Squad: ``CatastropheResponseSquad``.

CustomerServiceOrchestrator (customer_service_orchestrator)
    Handles ``customer_interaction_logged`` events.
    Pipeline: ClaimsTriageAgent (intent classification) → GuardAgent →
    AuditAgent → EscalationAgent (conditional).
    Squad: ``CustomerServiceSquad``.

AuditComplianceOrchestrator (audit_compliance_orchestrator)
    Handles ``audit_query_received`` events.
    Retrieves audit entries and assembles structured compliance reports.
    Squad: ``AuditComplianceSquad``.

Common Flow Contract
--------------------
All squad orchestrators return a composite result dict containing::

    {
        "status":         str,   # "completed" | "error"
        "squad_id":       str,   # squad name
        "event_id":       str,   # originating event ID
        "correlation_id": str,   # trace identifier
        ...                      # agent-specific results per step
    }

Framework Integration
---------------------
Orchestrators integrate with:

- ``BaseOrchestrator`` — governance hooks, Zero Trust layer, monitoring
- ``publish_status(status, context)`` — emits lifecycle events to K9EventBus
- ``apply_zero_trust(payload)`` — runtime ZTA enforcement (when enabled)
- ``apply_pre_governance / apply_post_governance`` — policy checks

Example Usage
-------------
::

    import asyncio
    from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator import EOCOrchestrator
    from k9_aif_abb.k9_utils.config_loader import load_yaml

    config = load_yaml("examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml")
    orchestrator = EOCOrchestrator(config=config)

    result = asyncio.run(orchestrator.execute_flow({
        "event_type": "claim_submitted",
        "intent": "claim_submitted",
        "event_id": "EVT-001",
        "claim_id": "CLM-001",
        "claimant_id": "C-100",
        "policy_id": "POL-500",
        "claim_type": "property_damage",
        "amount_claimed": 45000.00,
        "correlation_id": "eoc-trace-abc123",
    }))
    print(result["final_decision"], result["confidence"])
"""

