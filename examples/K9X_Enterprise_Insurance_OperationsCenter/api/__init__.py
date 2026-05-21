# SPDX-License-Identifier: Apache-2.0

"""
K9-AIF EOC — API Package
==========================

This package contains the **FastAPI event ingestion and query layer**
for the K9-AIF Enterprise Insurance Operations Center.

Modules
-------

app (app.py)
    The FastAPI application. Provides HTTP endpoints for event submission,
    audit queries, escalation queue management, and the Server-Sent Events
    (SSE) stream that powers the EOC Operations Dashboard.

    Key endpoints:

    ``POST /events/submit``
        Submit any enterprise event (ClaimSubmitted, DocumentReceived, etc.).
        The event is routed through EOCOrchestrator and the result is returned
        synchronously. Also published to Redpanda for async downstream consumers.

    ``GET /audit/query``
        Query the immutable audit trail. Supports filtering by
        ``correlation_id``, ``event_id``, ``agent_name``, and ``event_type``.

    ``GET /escalation/queue``
        Return all open HITL escalation tickets ordered by priority.

    ``POST /escalation/{ticket_id}/resolve``
        Mark an escalation ticket as resolved (operator action).

    ``GET /events/stream``
        Server-Sent Events stream. The EOC Dashboard subscribes here to
        receive live event feed updates as claims are processed.

    ``GET /health``
        System health check — returns service status and component availability.

models (models.py)
    Pydantic request/response models for all API endpoints.
    Provides input validation and OpenAPI schema generation.

    Key models:

    - ``EOCEvent`` — base envelope for all enterprise events
    - ``ClaimSubmittedEvent`` — typed claim submission payload
    - ``DocumentReceivedEvent`` — document upload payload
    - ``FraudSignalEvent`` — external fraud signal payload
    - ``AuditQueryRequest`` — audit query filter parameters
    - ``EscalationResolveRequest`` — HITL resolution payload
    - ``EOCEventResponse`` — standard API response envelope

Framework Integration
---------------------
The API layer integrates with:

- ``EOCOrchestrator`` — routes events through squad pipelines
- ``K9EventBus`` — publishes events to Redpanda for async processing
- ``AuditAgent`` — queries immutable audit records
- ``EscalationAgent`` — manages HITL escalation tickets
- FastAPI lifespan — bootstraps ``LLMFactory`` and ``ModelRouterFactory``
  on startup

Example curl Usage
------------------
::

    # Submit a claim
    curl -X POST http://localhost:8000/events/submit \\
         -H "Content-Type: application/json" \\
         -d '{
               "event_type": "claim_submitted",
               "claim_id": "CLM-001",
               "claimant_id": "C-100",
               "policy_id": "POL-500",
               "claim_type": "property_damage",
               "amount_claimed": 45000.00,
               "notes": "Water damage from burst pipe",
               "correlation_id": "eoc-trace-abc123"
             }'

    # Query audit trail
    curl "http://localhost:8000/audit/query?correlation_id=eoc-trace-abc123"

    # Get escalation queue
    curl http://localhost:8000/escalation/queue

Running the API
---------------
::

    cd /path/to/k9-aif-framework
    uvicorn examples.K9X_Enterprise_Insurance_OperationsCenter.api.app:app --reload --port 8000
"""
