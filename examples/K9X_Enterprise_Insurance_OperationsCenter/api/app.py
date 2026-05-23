# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — FastAPI Application

"""
EOC FastAPI Application
========================

Provides the HTTP layer for event ingestion, audit queries,
escalation queue management, and the SSE live event stream
consumed by the EOC Operations Dashboard.

Start with::

    uvicorn examples.K9X_Enterprise_Insurance_OperationsCenter.api.app:app --reload --port 8000
"""

import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.agent_loader import AgentLoader as _SBBAgentLoader

from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator import EOCOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.systems_check import run_all_checks
from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_model_router import EOCModelRouter, register_sse_callback as register_model_router_sse
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import register_sse_callback as register_llm_invoke_sse
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.audit_agent import AuditAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.escalation_agent import EscalationAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.api.models import (
    EOCEvent,
    ClaimSubmittedEvent,
    DocumentReceivedEvent,
    FraudSignalEvent,
    PolicyChangeEvent,
    CatastropheAlertEvent,
    CustomerInteractionEvent,
    AuditQueryRequest,
    EscalationResolveRequest,
    EOCEventResponse,
    HealthResponse,
    ScenarioRunRequest,
    ScenarioRunResponse,
    TraceStep,
)

log = logging.getLogger(__name__)

# ============================================================
# Agent YAML loader — drives trace enrichment (transparency)
# ============================================================
_AGENTS_YAML_DIR = Path(__file__).parent.parent / "agents" / "yaml"
_AGENT_LOADER = _SBBAgentLoader(_AGENTS_YAML_DIR)

# Model catalog — mirrors config.yaml inference.model_catalog
_MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "general":    {"model_id": "llama3.2:1b",          "provider": "ollama", "cost": "minimal",  "latency": "realtime",    "caps": ["chat", "summarization", "customer_intent"]},
    "reasoning":  {"model_id": "granite3-dense:2b",    "provider": "ollama", "cost": "standard", "latency": "interactive", "caps": ["reasoning", "adjudication", "fraud", "audit_report"]},
    "guardian":   {"model_id": "granite3-guardian",    "provider": "ollama", "cost": "standard", "latency": "interactive", "caps": ["guardrails", "pii_detection", "policy_compliance"]},
    "extraction": {"model_id": "granite3-dense:2b",    "provider": "ollama", "cost": "standard", "latency": "batch",       "caps": ["extraction", "structured_output", "ocr_post_processing"]},
}

# Estimated latency per component (ms) — used for transparency display
_COMPONENT_LATENCY: Dict[str, int] = {
    "EOCRouter": 6, "EOCOrchestrator": 11, "SquadLoader": 22,
    "ClaimsTriageAgent": 320, "AdjudicationAgent": 680,
    "DocumentExtractorAgent": 450, "FraudDetectionAgent": 510,
    "GraphSyncAgent": 42, "GuardAgent": 270,
    "AuditAgent": 33, "EscalationAgent": 18,
    "EscalationGate": 4, "PolicyDecision": 8, "AuditQuery": 28, "Pipeline": 2,
}

# Maps agent class name → result dict key
_AGENT_RESULT_KEY: Dict[str, Any] = {
    "ClaimsTriageAgent": "triage", "AdjudicationAgent": "adjudication",
    "DocumentExtractorAgent": "extraction", "FraudDetectionAgent": ["fraud_assessment", "impact_assessment"],
    "GraphSyncAgent": "graph_sync", "GuardAgent": "guard",
    "AuditAgent": "audit", "EscalationAgent": "escalation",
}

# ============================================================
# Module-level state
# ============================================================
_config: Dict[str, Any] = {}
_orchestrator: Optional[EOCOrchestrator] = None
_audit_agent: Optional[AuditAgent] = None

# In-memory SSE event queue (per-process demo; use Redis in production)
_sse_events: List[Dict[str, Any]] = []
_MAX_SSE_HISTORY = 200

# Kafka producer (set when K9_KAFKA_MODE=1)
_kafka_producer = None
_KAFKA_INBOUND_TOPIC  = "eoc-events"
_KAFKA_RESULTS_TOPIC  = "eoc-results"
_KAFKA_PIPELINE_TIMEOUT = int(os.environ.get("K9_PIPELINE_TIMEOUT", "180"))

# Pending pipeline results: correlation_id → asyncio.Future (resolved by results consumer thread)
_pending_results: Dict[str, Any] = {}
_pending_lock = threading.Lock()
_kafka_loop: Optional[Any] = None   # event loop reference for call_soon_threadsafe





# ============================================================
# Lifespan — bootstrap on startup
# ============================================================
def _start_kafka_results_consumer(brokers: list, loop) -> None:
    """Background thread: consume eoc-results, resolve waiting run_scenario futures, push SSE."""
    global _kafka_loop
    _kafka_loop = loop
    try:
        from kafka import KafkaConsumer as _KC
        consumer = _KC(
            _KAFKA_RESULTS_TOPIC,
            bootstrap_servers=brokers,
            group_id="eoc-app-results",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
        )
        print(f"[EOC API] Kafka results consumer ready — topic={_KAFKA_RESULTS_TOPIC}")
        for msg in consumer:
            payload = msg.value

            # LLMCall trace events forwarded from the orchestrator process — push directly to SSE.
            if payload.get("type") == "LLMCall":
                _push_sse(payload)
                continue

            corr_id = payload.get("correlation_id", "")
            result  = payload.get("result", {})

            # Resolve the waiting run_scenario future (if any)
            if corr_id:
                with _pending_lock:
                    fut = _pending_results.pop(corr_id, None)
                if fut is not None and not fut.done():
                    loop.call_soon_threadsafe(fut.set_result, payload)

            # SSE live-feed push (unchanged)
            _push_sse({
                "type": "KafkaResult",
                "event_type": payload.get("event_type"),
                "event_id": payload.get("event_id"),
                "correlation_id": corr_id,
                "status": result.get("status"),
                "final_decision": result.get("final_decision"),
                "confidence": result.get("confidence"),
                "escalated": bool((result.get("escalation") or {}).get("should_escalate")),
            })
    except Exception as exc:
        print(f"[EOC API] Kafka results consumer error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _orchestrator, _audit_agent, _kafka_producer

    _config = load_yaml(
        "examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml"
    )

    if not run_all_checks(_config):
        log.error("EOC system checks failed — server will not start.")
        raise SystemExit(1)

    LLMFactory.bootstrap(_config)

    # Build EOCModelRouter (our SBB) and inject it into the factory cache so
    # all agents receive it when they call ModelRouterFactory.get_router().
    _norm  = ModelRouterFactory._normalize_config(_config)
    _cat   = ModelRouterFactory._build_catalog(_norm)
    _store = ModelRouterFactory._build_router_state_store(_norm)
    _eoc_router = EOCModelRouter(catalog=_cat, config=_norm, state_store=_store)
    _router_key = "k9_model_router:True:postgres"
    ModelRouterFactory._instances[_router_key] = _eoc_router
    register_model_router_sse(_push_sse)
    register_llm_invoke_sse(_push_sse)
    log.info("[EOC API] EOCModelRouter injected into factory cache (key=%s)", _router_key)

    _orchestrator = EOCOrchestrator(config=_config)
    _audit_agent = AuditAgent(config=_config)

    # Kafka mode: wire up producer + background SSE consumer
    if os.environ.get("K9_KAFKA_MODE", "").strip() in ("1", "true", "yes"):
        try:
            from kafka import KafkaProducer as _KP
            brokers_raw = (
                os.environ.get("K9_KAFKA_BROKERS")
                or ",".join(_config.get("messaging", {}).get("brokers", ["localhost:9092"]))
            )
            brokers = [b.strip() for b in brokers_raw.split(",") if b.strip()]
            _kafka_producer = _KP(
                bootstrap_servers=brokers,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                acks="all",                      # wait for leader ack (single-node = same as acks=1)
                linger_ms=0,                 # send immediately, no batching delay
                connections_max_idle_ms=270000,  # stay under Redpanda's idle timeout
            )
            loop = asyncio.get_event_loop()
            t = threading.Thread(
                target=_start_kafka_results_consumer,
                args=(brokers, loop),
                daemon=True,
                name="kafka-results-consumer",
            )
            t.start()
            print(f"[EOC API] Kafka mode ACTIVE | brokers={brokers} | inbound={_KAFKA_INBOUND_TOPIC}")
        except Exception as exc:
            print(f"[EOC API] Kafka mode init failed (falling back to direct): {exc}")
            _kafka_producer = None
    else:
        print("[EOC API] Direct mode (no Kafka) — EOCOrchestrator handling events in-process")

    print("[EOC API] Startup complete — EOCOrchestrator ready")
    yield
    if _kafka_producer:
        try:
            _kafka_producer.flush()
            _kafka_producer.close()
        except Exception:
            pass
    print("[EOC API] Shutdown")


# ============================================================
# App
# ============================================================
app = FastAPI(
    title="K9-AIF Enterprise Insurance Operations Center API",
    description=(
        "Event ingestion, audit query, and HITL escalation management API "
        "for the K9-AIF EOC reference application. "
        "Every event flows through the governed K9-AIF squad pipeline."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Helpers
# ============================================================
def _push_sse(event: Dict[str, Any]):
    _sse_events.append({**event, "_ts": datetime.now(timezone.utc).isoformat()})
    if len(_sse_events) > _MAX_SSE_HISTORY:
        _sse_events.pop(0)


def _build_response(result: Dict[str, Any], event_id: str, correlation_id: str) -> EOCEventResponse:
    escalation = result.get("escalation") or {}
    audit = result.get("audit") or {}
    return EOCEventResponse(
        status=result.get("status", "completed"),
        event_id=event_id,
        correlation_id=correlation_id,
        squad_id=result.get("squad_id"),
        final_decision=result.get("final_decision") or result.get("policy_decision"),
        confidence=result.get("confidence"),
        escalated=bool(escalation.get("should_escalate")),
        ticket_id=escalation.get("ticket_id"),
        audit_id=audit.get("audit_id"),
        details=result,
    )


# ============================================================
# Health
# ============================================================
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """System health check. Returns service status and component availability."""
    return HealthResponse(
        status="ok",
        components={
            "orchestrator": "ready" if _orchestrator else "not_initialized",
            "audit_agent": "ready" if _audit_agent else "not_initialized",
            "llm_factory": "ready" if LLMFactory.is_bootstrapped() else "stub_mode",
        },
    )


# ============================================================
# Event Submission
# ============================================================
@app.post("/events/submit", response_model=EOCEventResponse, tags=["Events"])
async def submit_event(event: EOCEvent):
    """
    Submit any enterprise event to the EOC pipeline.

    The event is routed through the EOCOrchestrator → appropriate squad
    orchestrator → agent pipeline. Results are returned synchronously.
    The event and its processing result are also pushed to the SSE stream.

    Supported event_type values:
    - ``claim_submitted``
    - ``document_received``
    - ``fraud_signal_raised``
    - ``policy_change_requested``
    - ``catastrophe_alert_issued``
    - ``customer_interaction_logged``
    - ``audit_query_received``
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="EOC orchestrator not initialized")

    payload = event.model_dump()
    payload["intent"] = event.event_type
    payload.setdefault("event_id", f"EVT-{uuid.uuid4().hex[:8].upper()}")
    payload.setdefault("correlation_id", str(uuid.uuid4()))

    _push_sse({
        "type": "EventReceived",
        "event_type": event.event_type,
        "event_id": payload["event_id"],
        "correlation_id": payload["correlation_id"],
    })

    # Kafka mode: publish to eoc-events and return 202 Accepted
    if _kafka_producer is not None:
        try:
            loop = asyncio.get_event_loop()
            future = _kafka_producer.send(_KAFKA_INBOUND_TOPIC, value=payload)
            meta = await loop.run_in_executor(None, lambda: future.get(timeout=10))
            log.info(
                "[EOC API] Kafka ACK event_type=%s topic=%s partition=%d offset=%d",
                event.event_type, meta.topic, meta.partition, meta.offset,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Kafka publish error: {exc}")
        return EOCEventResponse(
            status="accepted",
            event_id=payload["event_id"],
            correlation_id=payload["correlation_id"],
            details={"message": f"Event queued → {_KAFKA_INBOUND_TOPIC}. Result arrives via SSE stream."},
        )

    # Direct mode: call EOCOrchestrator in-process
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="EOC orchestrator not initialized")

    try:
        result = await _orchestrator.execute_flow(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    _push_sse({
        "type": "EventProcessed",
        "event_type": event.event_type,
        "event_id": payload["event_id"],
        "correlation_id": payload["correlation_id"],
        "status": result.get("status"),
        "final_decision": result.get("final_decision"),
        "confidence": result.get("confidence"),
        "escalated": bool((result.get("escalation") or {}).get("should_escalate")),
    })

    return _build_response(result, payload["event_id"], payload["correlation_id"])


@app.post("/events/claim", response_model=EOCEventResponse, tags=["Events"])
async def submit_claim(event: ClaimSubmittedEvent):
    """Submit a typed ClaimSubmitted event with field validation."""
    return await submit_event(event)


@app.post("/events/document", response_model=EOCEventResponse, tags=["Events"])
async def submit_document(event: DocumentReceivedEvent):
    """Submit a typed DocumentReceived event with field validation."""
    return await submit_event(event)


@app.post("/events/fraud-signal", response_model=EOCEventResponse, tags=["Events"])
async def submit_fraud_signal(event: FraudSignalEvent):
    """Submit a typed FraudSignalRaised event with field validation."""
    return await submit_event(event)


@app.post("/events/policy-change", response_model=EOCEventResponse, tags=["Events"])
async def submit_policy_change(event: PolicyChangeEvent):
    """Submit a typed PolicyChangeRequested event with field validation."""
    return await submit_event(event)


@app.post("/events/catastrophe", response_model=EOCEventResponse, tags=["Events"])
async def submit_catastrophe(event: CatastropheAlertEvent):
    """Submit a typed CatastropheAlertIssued event with field validation."""
    return await submit_event(event)


@app.post("/events/customer-interaction", response_model=EOCEventResponse, tags=["Events"])
async def submit_customer_interaction(event: CustomerInteractionEvent):
    """Submit a typed CustomerInteractionLogged event with field validation."""
    return await submit_event(event)


# ============================================================
# Audit
# ============================================================
@app.get("/audit/query", tags=["Audit"])
async def query_audit(
    correlation_id: Optional[str] = Query(None, description="Filter by correlation ID"),
    event_id: Optional[str] = Query(None, description="Filter by event ID"),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
):
    """
    Query the immutable EOC audit trail.

    Returns AuditEntry records filtered by the provided parameters.
    Records are ordered by timestamp descending (most recent first).
    """
    if not _audit_agent:
        raise HTTPException(status_code=503, detail="Audit agent not initialized")

    result = _audit_agent.execute({
        "audit_mode": "query",
        "correlation_id": correlation_id,
        "event_id": event_id,
        "agent_name": agent_name,
        "event_type": event_type,
        "limit": limit,
    })
    return result


# ============================================================
# Escalation Queue
# ============================================================
@app.get("/escalation/queue", tags=["Escalation"])
async def get_escalation_queue():
    """
    Return all open HITL escalation tickets ordered by priority.

    Reads from the ``escalation_tickets`` table in the EOC database.
    In Phase 1 this returns from the in-memory SSE event log as a stub;
    Phase 2 wires it to the actual database.
    """
    open_escalations = [
        e for e in _sse_events
        if e.get("type") == "EventProcessed" and e.get("escalated")
    ]
    return {
        "count": len(open_escalations),
        "tickets": open_escalations,
        "note": "Phase 1: sourced from SSE event log. Phase 2 wires to escalation_tickets table.",
    }


@app.post("/escalation/{ticket_id}/resolve", tags=["Escalation"])
async def resolve_escalation(ticket_id: str, body: EscalationResolveRequest):
    """
    Mark a HITL escalation ticket as resolved.

    Records the operator's resolution decision and writes a final
    AuditEntry with the operator_id for compliance traceability.
    """
    if not _audit_agent:
        raise HTTPException(status_code=503, detail="Audit agent not initialized")

    audit_result = _audit_agent.execute({
        "event_id": ticket_id,
        "event_type": "escalation_resolved",
        "squad_id": "HumanEscalationQueue",
        "source_agent": "HumanOperator",
        "confidence": 1.0,
        "decision": body.resolution,
        "response_text": body.resolution_notes or "",
        "operator_id": body.operator_id,
        "correlation_id": ticket_id,
    })

    _push_sse({
        "type": "EscalationResolved",
        "ticket_id": ticket_id,
        "resolution": body.resolution,
        "operator_id": body.operator_id,
    })

    return {
        "status": "resolved",
        "ticket_id": ticket_id,
        "resolution": body.resolution,
        "audit_id": audit_result.get("audit_id"),
    }


# ============================================================
# SSE Live Event Stream
# ============================================================
@app.get("/events/stream", tags=["Dashboard"])
async def event_stream():
    """
    Server-Sent Events stream for the EOC Operations Dashboard.

    Streams all recent EOC events (submitted and processed) in real time.
    The dashboard subscribes to this endpoint and renders the Live Event Feed,
    Agent Activity Monitor, and Escalation Queue panels.

    Connect with ``EventSource`` in the browser::

        const es = new EventSource('/events/stream');
        es.onmessage = e => console.log(JSON.parse(e.data));
    """
    async def generator() -> AsyncGenerator[str, None]:
        last_sent = 0
        while True:
            current = len(_sse_events)
            if current > last_sent:
                for evt in _sse_events[last_sent:current]:
                    yield f"data: {json.dumps(evt)}\n\n"
                last_sent = current
            await asyncio.sleep(0.5)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# Recent Events (for dashboard polling fallback)
# ============================================================
@app.get("/events/recent", tags=["Dashboard"])
async def recent_events(limit: int = Query(50, ge=1, le=200)):
    """Return the most recent N events from the in-process event log."""
    return {
        "count": min(limit, len(_sse_events)),
        "events": _sse_events[-limit:],
    }


# ============================================================
# Architecture Demo — scenario metadata + sample payloads
# ============================================================

_SCENARIO_META: Dict[str, Dict[str, Any]] = {
    "claim_submitted": {
        "id": "claim_submitted", "label": "Claim Submitted", "icon": "📋",
        "squad": "ClaimsProcessingSquad", "orchestrator": "ClaimsProcessingOrchestrator",
        "topic": "eoc-claims",
        "agents": ["ClaimsTriageAgent", "AdjudicationAgent", "GuardAgent", "AuditAgent"],
        "conditional_agents": ["EscalationAgent"],
        "description": "End-to-end claim ingestion — triage, LLM adjudication, governance guard, immutable audit.",
        "result_keys": ["triage", "adjudication", "guard", "audit", "escalation"],
    },
    "document_received": {
        "id": "document_received", "label": "Document Received", "icon": "📄",
        "squad": "DocumentIntelligenceSquad", "orchestrator": "DocumentIntelligenceOrchestrator",
        "topic": "eoc-documents",
        "agents": ["DocumentExtractorAgent", "GuardAgent", "GraphSyncAgent", "AuditAgent"],
        "conditional_agents": [],
        "description": "OCR extraction, structured JSON output, PII guard, graph relationship sync, audit.",
        "result_keys": ["extraction", "guard", "graph_sync", "audit"],
    },
    "fraud_signal_raised": {
        "id": "fraud_signal_raised", "label": "Fraud Signal Raised", "icon": "🚨",
        "squad": "RiskAssessmentSquad", "orchestrator": "RiskAssessmentOrchestrator",
        "topic": "eoc-fraud",
        "agents": ["FraudDetectionAgent", "GuardAgent", "AuditAgent"],
        "conditional_agents": ["EscalationAgent"],
        "description": "Multi-signal fraud correlation, risk scoring, governance guard, conditional HITL escalation.",
        "result_keys": ["fraud_assessment", "guard", "audit", "escalation"],
    },
    "policy_change_requested": {
        "id": "policy_change_requested", "label": "Policy Change Requested", "icon": "📝",
        "squad": "PolicyManagementSquad", "orchestrator": "PolicyManagementOrchestrator",
        "topic": "eoc-policy",
        "agents": ["GuardAgent", "AuditAgent"],
        "conditional_agents": [],
        "description": "Policy change validation — governance guard pre-screens the request, audit records the outcome.",
        "result_keys": ["guard", "audit", "policy_decision"],
    },
    "catastrophe_alert_issued": {
        "id": "catastrophe_alert_issued", "label": "Catastrophe Alert Issued", "icon": "⚠️",
        "squad": "CatastropheResponseSquad", "orchestrator": "CatastropheResponseOrchestrator",
        "topic": "eoc-catastrophe",
        "agents": ["FraudDetectionAgent", "AuditAgent"],
        "conditional_agents": [],
        "description": "Mass-loss event triage — exposure assessment, risk scoring, response plan generation, audit.",
        "result_keys": ["impact_assessment", "audit", "response_plan"],
    },
    "customer_interaction_logged": {
        "id": "customer_interaction_logged", "label": "Customer Interaction", "icon": "💬",
        "squad": "CustomerServiceSquad", "orchestrator": "CustomerServiceOrchestrator",
        "topic": "eoc-customer",
        "agents": ["ClaimsTriageAgent", "GuardAgent", "AuditAgent"],
        "conditional_agents": ["EscalationAgent"],
        "description": "Inbound customer interaction — intent detection, PII guard, audit, conditional escalation.",
        "result_keys": ["intent", "guard", "audit", "escalation"],
    },
    "audit_query_received": {
        "id": "audit_query_received", "label": "Audit Query", "icon": "🔍",
        "squad": "AuditComplianceSquad", "orchestrator": "AuditComplianceOrchestrator",
        "topic": "eoc-audit",
        "agents": ["AuditAgent"],
        "conditional_agents": [],
        "description": "Compliance audit retrieval — immutable audit trail query with compliance report generation.",
        "result_keys": ["audit_entries", "compliance_report"],
    },
}

_SAMPLE_PAYLOADS: Dict[str, Dict[str, Any]] = {
    "claim_submitted": {
        "claimant_id": "CLM-2891", "claim_id": "CLM-2024-09112",
        "policy_id": "POL-HOME-4422",
        "claim_type": "property_damage", "amount_claimed": 47500,
        "notes": "Roof and siding damage from hail storm — June 14 incident. Three contractors assessed.",
        "is_repeat_claimant": False,
    },
    "document_received": {
        "filename": "adjuster_report_2891.pdf", "claimant_id": "CLM-2891",
        "claim_id": "CLM-2024-09112", "file_type": "application/pdf",
        "raw_text": "PROPERTY DAMAGE ASSESSMENT\nPolicy: POL-HOME-4422\nClaimant: J. Westbrook\nIncident Date: 2024-06-14\nType: Hail Damage — Roof and Siding\nEstimated Loss: $47,500\nAdjuster: R. Malone, Lic. #TX-4421\nSignature: Present",
    },
    "fraud_signal_raised": {
        "alert_source": "ClaimsAnalyticsEngine", "claimant_id": "CLM-7734",
        "claim_id": "CLM-2024-07891", "policy_id": "POL-PROP-3317",
        "severity": "high", "amount_claimed": 128000,
        "description": "Third property claim in 90-day window. Same vendor cited on all three. Duplicate invoice amounts detected.",
    },
    "policy_change_requested": {
        "policy_id": "POL-AUTO-9923", "change_type": "endorsement",
        "change_description": "Add comprehensive flood coverage rider. Effective date: immediate.",
        "notes": "Agent: Maria Santos | Branch: Austin TX",
    },
    "catastrophe_alert_issued": {
        "alert_description": "Category 4 hurricane landfall — Gulf Coast, LA/TX/MS. Wind 145mph. 12,000+ affected policyholders.",
        "estimated_exposure": 2_400_000_000,
        "affected_regions": ["Louisiana", "Texas", "Mississippi"], "severity": "critical",
    },
    "customer_interaction_logged": {
        "customer_id": "CUST-8821", "interaction_type": "claim_status",
        "customer_message": "I submitted claim CLM-2024-09112 three weeks ago and have not received any updates. The damage is extensive.",
        "channel": "portal", "policy_id": "POL-HOME-4422",
    },
    "audit_query_received": {"audit_mode": "query", "limit": 10},
}

# Result-key → (agent display name, trace layer, message builder)
_RESULT_KEY_META: Dict[str, tuple] = {
    "triage":            ("ClaimsTriageAgent",      "agent",      lambda r: f"Priority: {r.get('priority','?').upper()} | Completeness: {r.get('completeness_score',0):.0%} | Coverage: {'✓' if r.get('coverage_match') else '✗'}"),
    "adjudication":      ("AdjudicationAgent",      "agent",      lambda r: f"Decision: {str(r.get('decision','?')).upper()} | Confidence: {r.get('confidence',0):.0%}"),
    "extraction":        ("DocumentExtractorAgent", "agent",      lambda r: f"Status: {r.get('validation_status','?')} | OCR: {'yes' if r.get('ocr_applied') else 'no'} | Type: {r.get('classification','?')}"),
    "fraud_assessment":  ("FraudDetectionAgent",    "agent",      lambda r: f"Risk score: {r.get('risk_score',0):.2f} | Rec: {r.get('recommendation','?')}"),
    "impact_assessment": ("FraudDetectionAgent",    "agent",      lambda r: f"Risk score: {r.get('risk_score',0):.2f} | Rec: {r.get('recommendation','?')}"),
    "intent":            ("ClaimsTriageAgent",      "agent",      lambda r: f"Priority: {r.get('priority','?').upper()} | Confidence: {r.get('confidence',0):.0%}"),
    "graph_sync":        ("GraphSyncAgent",         "agent",      lambda r: f"Nodes: {r.get('nodes_created',0)} | Edges: {r.get('relationships_created',0)}"),
    "guard":             ("GuardAgent",             "governance", lambda r: f"Guard {'PASSED ✓' if r.get('passed') else 'FAILED ✗'} | PII: {r.get('pii_detected', False)} | Tokens issued: {len(r.get('token_vault') or [])}"),
    "audit":             ("AuditAgent",             "audit",      lambda r: f"Audit record: {r.get('audit_id','N/A')}"),
    "escalation":        ("EscalationAgent",        "escalation", lambda r: f"HITL ticket: {r.get('ticket_id','N/A')}"),
}


def _enrich_step(step: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Add full agent transparency fields (YAML, model routing, governance, latency, result) to a trace step."""
    component = step["component"]
    step["latency_ms"] = _COMPONENT_LATENCY.get(component, 10)

    yaml_cfg = _AGENT_LOADER._by_class.get(component, {})
    if not yaml_cfg:
        return step

    model_key = yaml_cfg.get("model", "general")
    mc = _MODEL_CATALOG.get(model_key, {})
    mr = yaml_cfg.get("model_routing", {})

    step["agent_yaml"] = {
        "name": yaml_cfg.get("name", component),
        "description": str(yaml_cfg.get("description", "")).strip(),
        "pattern": yaml_cfg.get("pattern", ""),
        "model": model_key,
        "role": str(yaml_cfg.get("role", "")).strip(),
        "goal": str(yaml_cfg.get("goal", "")).strip(),
        "instructions": yaml_cfg.get("instructions", []),
        "output_schema": yaml_cfg.get("output_schema", {}),
        "governance": yaml_cfg.get("governance", {}),
        "routing": yaml_cfg.get("routing", {}),
    }
    step["model_routing"] = {
        "model_key": model_key,
        "model_id": mc.get("model_id", "?"),
        "provider": mc.get("provider", "?"),
        "cost_profile": mc.get("cost", "?"),
        "latency_budget": mc.get("latency", "?"),
        "capabilities": mc.get("caps", []),
        "task_type": mr.get("task_type", ""),
        "primary_model": mr.get("primary_model", model_key),
        "fallback_model": mr.get("fallback_model"),
        "rationale": mr.get("rationale", ""),
        "compliance_note": mr.get("compliance_note", ""),
    }
    gov = yaml_cfg.get("governance", {})
    step["governance_detail"] = {
        "pre_guard": gov.get("pre_process", False),
        "post_guard": gov.get("post_process", False),
        "note": gov.get("note", ""),
        "confidence_threshold": 0.75 if component in ("AdjudicationAgent", "FraudDetectionAgent", "ClaimsTriageAgent") else None,
        "pii_fields_scanned": ["ssn", "date_of_birth", "bank_account", "credit_card", "phone_number", "email"] if gov.get("pre_process") or gov.get("post_process") else [],
        "hard_gate": component == "GuardAgent",
    }
    step["tools"] = yaml_cfg.get("tools", [])

    rkey = _AGENT_RESULT_KEY.get(component)
    if rkey:
        if isinstance(rkey, list):
            for k in rkey:
                if k in result:
                    step["agent_result"] = result[k]
                    break
        elif rkey in result:
            step["agent_result"] = result[rkey]

    return step


def _extract_trace(event_type: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a step-by-step trace list from the raw pipeline result dict."""
    meta = _SCENARIO_META.get(event_type, {})
    squad_id = result.get("squad_id", meta.get("squad", ""))
    n_agents = len(meta.get("agents", [])) + len(meta.get("conditional_agents", []))

    trace = [
        {"step": 1, "component": "EOCRouter",       "layer": "router",       "status": "ok",
         "message": f"event_type='{event_type}' matched → topic: {meta.get('topic','?')}"},
        {"step": 2, "component": "EOCOrchestrator", "layer": "orchestrator", "status": "ok",
         "message": f"Dispatching to {squad_id}"},
        {"step": 3, "component": "SquadLoader",     "layer": "squad",        "status": "ok",
         "message": f"Squad '{squad_id}' loaded — {n_agents} agents initialized"},
    ]

    step = 4
    for key in ["triage", "extraction", "fraud_assessment", "impact_assessment", "intent",
                "adjudication", "graph_sync", "guard", "audit"]:
        val = result.get(key)
        if not (val and isinstance(val, dict)):
            continue
        agent_name, layer, summarize = _RESULT_KEY_META[key]
        status = "warn" if (key == "guard" and not val.get("passed", True)) else "ok"
        try:
            msg = summarize(val)
        except Exception:
            msg = str(val)[:120]
        trace.append({"step": step, "component": agent_name, "layer": layer, "status": status, "message": msg})
        step += 1

    # Escalation (conditional)
    escalation = result.get("escalation")
    if escalation and isinstance(escalation, dict):
        _, _, summarize = _RESULT_KEY_META["escalation"]
        trace.append({"step": step, "component": "EscalationAgent", "layer": "escalation", "status": "warn",
                      "message": summarize(escalation)})
        step += 1
    elif squad_id in ("ClaimsProcessingSquad", "RiskAssessmentSquad", "CustomerServiceSquad"):
        trace.append({"step": step, "component": "EscalationGate", "layer": "escalation", "status": "ok",
                      "message": "Confidence ≥ threshold — escalation gate bypassed"})
        step += 1

    # Special result fields
    if "policy_decision" in result:
        trace.append({"step": step, "component": "PolicyDecision", "layer": "result", "status": "ok",
                      "message": f"Policy decision: {str(result['policy_decision']).upper()}"})
        step += 1
    if "audit_entries" in result:
        trace.append({"step": step, "component": "AuditQuery", "layer": "audit", "status": "ok",
                      "message": f"Compliance query returned {result.get('entry_count', 0)} audit entries"})
        step += 1

    trace.append({"step": step, "component": "Pipeline", "layer": "result", "status": "ok",
                  "message": f"Flow complete — status='{result.get('status','completed')}' squad='{squad_id}'",
                  "final": True})

    return [_enrich_step(t, result) for t in trace]


# ============================================================
# Architecture Demo Endpoints
# ============================================================

@app.get("/api/eoc/scenarios", tags=["Architecture Demo"])
async def get_scenarios():
    """
    Return all seven EOC event scenarios with metadata and sample payloads.

    Used by the web UI to populate the scenario selector and payload editor.
    """
    return {
        "scenarios": [
            {**meta, "sample_payload": _SAMPLE_PAYLOADS.get(sid, {})}
            for sid, meta in _SCENARIO_META.items()
        ]
    }


@app.post("/api/eoc/run", response_model=ScenarioRunResponse, tags=["Architecture Demo"])
async def run_scenario(body: ScenarioRunRequest):
    """
    Execute a named scenario through the full K9-AIF pipeline.

    Accepts an ``event_type`` and optional ``payload`` (defaults to the built-in
    sample if omitted).  Returns the annotated step-by-step runtime trace plus
    the raw pipeline result — both are used by the EOC Operations Dashboard.
    """
    if body.event_type not in _SCENARIO_META:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event_type '{body.event_type}'. Valid: {list(_SCENARIO_META)}",
        )

    payload: Dict[str, Any] = dict(body.payload or _SAMPLE_PAYLOADS.get(body.event_type, {}))
    payload["event_type"] = body.event_type
    payload.setdefault("event_id", f"EVT-{uuid.uuid4().hex[:8].upper()}")
    payload.setdefault("correlation_id", str(uuid.uuid4()))
    corr_id = payload["correlation_id"]

    error: Optional[str] = None
    result: Dict[str, Any] = {}

    if _kafka_producer is not None:
        # ── Kafka mode: publish → wait for pipeline result on eoc-results ──────
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        with _pending_lock:
            _pending_results[corr_id] = fut
        try:
            future = _kafka_producer.send(_KAFKA_INBOUND_TOPIC, value=payload)
            meta = await loop.run_in_executor(None, lambda: future.get(timeout=10))
            log.info(
                "[EOC API] Kafka ACK event_type=%s topic=%s partition=%d offset=%d corr=%s",
                body.event_type, meta.topic, meta.partition, meta.offset, corr_id,
            )
        except Exception as exc:
            with _pending_lock:
                _pending_results.pop(corr_id, None)
            error = f"Kafka publish failed: {exc}"
            result = {"status": "error", "detail": error,
                      "squad_id": _SCENARIO_META[body.event_type]["squad"]}
        else:
            try:
                kafka_payload = await asyncio.wait_for(asyncio.shield(fut), timeout=_KAFKA_PIPELINE_TIMEOUT)
                result = kafka_payload.get("result", {})
                print(f"[EOC API] ✓ Pipeline result received corr={corr_id} status={result.get('status')}", flush=True)
            except asyncio.TimeoutError:
                with _pending_lock:
                    _pending_results.pop(corr_id, None)
                error = f"Pipeline timeout — router or orchestrator did not respond within {_KAFKA_PIPELINE_TIMEOUT}s"
                result = {
                    "status": "timeout",
                    "detail": error,
                    "squad_id": _SCENARIO_META[body.event_type]["squad"],
                }
                print(f"[EOC API] ✗ {error}", flush=True)
    else:
        # ── Direct mode (no Kafka): run in-process ────────────────────────────
        if _orchestrator:
            try:
                result = await _orchestrator.execute_flow(payload)
            except Exception as exc:
                error = str(exc)
                result = {"status": "error", "detail": error,
                          "squad_id": _SCENARIO_META[body.event_type]["squad"]}
        else:
            error = "EOC orchestrator not initialized (stub mode)"
            result = {"status": "stub", "squad_id": _SCENARIO_META[body.event_type]["squad"]}

    trace_dicts = _extract_trace(body.event_type, result)
    if error:
        # Mark the last non-final step as error
        for t in reversed(trace_dicts):
            if not t.get("final"):
                t["status"] = "error"
                t["message"] = f"Pipeline error: {error}"
                break

    _push_sse({
        "type": "ScenarioRun",
        "event_type": body.event_type,
        "event_id": payload["event_id"],
        "correlation_id": payload["correlation_id"],
        "status": result.get("status", "completed"),
    })

    return ScenarioRunResponse(
        event_type=body.event_type,
        event_id=payload["event_id"],
        correlation_id=payload["correlation_id"],
        squad_id=result.get("squad_id"),
        trace=[TraceStep(**t) for t in trace_dicts],
        result=result,
        error=error,
    )


@app.get("/api/eoc/architecture", tags=["Architecture Demo"])
async def get_architecture():
    """
    Return the full K9-AIF EOC architecture metadata.

    Includes router routing table, all squad orchestrators and their agent
    pipelines, agent YAML configuration, governance policies, and model routing.
    Used by the Architecture Inspection tabs in the web UI.
    """
    return {
        "framework": "K9-AIF",
        "version": "0.1.0",
        "pattern": "Router → Orchestrator → SquadLoader → Squad → Agents → Guard → Audit → Result",
        "router": {
            "class": "EOCRouter",
            "description": "Deterministic event router. Inspects event_type, publishes to Kafka topic for the target squad orchestrator.",
            "routing_table": {sid: m["topic"] for sid, m in _SCENARIO_META.items()},
        },
        "orchestrator": {
            "class": "EOCOrchestrator",
            "description": "HTTP-mode dispatch adapter. Loads all seven squad orchestrators at startup, routes execute_flow() calls synchronously without Kafka.",
        },
        "squads": [
            {
                "id": m["squad"],
                "orchestrator": m["orchestrator"],
                "event_type": sid,
                "agents": m["agents"],
                "conditional_agents": m["conditional_agents"],
                "description": m["description"],
            }
            for sid, m in _SCENARIO_META.items()
        ],
        "agents": [
            {"class": "ClaimsTriageAgent",      "pattern": "reasoning",  "model": "reasoning",  "governance": {"pre": True,  "post": False}},
            {"class": "AdjudicationAgent",       "pattern": "reasoning",  "model": "reasoning",  "governance": {"pre": True,  "post": True}},
            {"class": "DocumentExtractorAgent",  "pattern": "extraction", "model": "extraction", "governance": {"pre": False, "post": False}},
            {"class": "FraudDetectionAgent",     "pattern": "reasoning",  "model": "reasoning",  "governance": {"pre": True,  "post": True}},
            {"class": "GraphSyncAgent",          "pattern": "tool",       "model": "general",    "governance": {"pre": False, "post": False}},
            {"class": "GuardAgent",              "pattern": "guard",      "model": "guardian",   "governance": {"pre": False, "post": False}, "note": "IS the governance implementation — uses Granite Guardian, no fallback"},
            {"class": "AuditAgent",              "pattern": "audit",      "model": "general",    "governance": {"pre": False, "post": False}},
            {"class": "EscalationAgent",         "pattern": "tool",       "model": "general",    "governance": {"pre": False, "post": False}},
        ],
        "governance": {
            "pii_guard":              {"enabled": True,  "model": "guardian", "description": "Detect and mask PII before LLM endpoints"},
            "confidence_threshold":   {"enabled": True,  "threshold": 0.75,   "description": "Escalate to HITL when confidence < 0.75"},
            "audit_all_actions":      {"enabled": True,                       "description": "Every agent action produces an immutable AuditEntry"},
            "no_fallback_compliance": {"enabled": True,                       "description": "Guardian is a hard requirement for policy checks — no fallback"},
            "zero_trust":             {"enabled": True,  "deny": 0.85, "approve": 0.75, "description": "K9 Zero Trust execution layer on all flows"},
        },
        "model_routing": {
            "general":    {"provider": "ollama", "model": "llama3.2:1b",           "capabilities": ["chat", "summarization", "customer_intent"]},
            "reasoning":  {"provider": "ollama", "model": "granite3-dense:2b",     "capabilities": ["reasoning", "adjudication", "fraud", "audit_report"]},
            "guardian":   {"provider": "ollama", "model": "granite3-guardian",     "capabilities": ["guardrails", "pii_detection", "policy_compliance"]},
            "extraction": {"provider": "ollama", "model": "granite3-dense:2b",     "capabilities": ["extraction", "structured_output", "ocr_post_processing"]},
        },
    }


@app.get("/api/eoc/config-summary", tags=["Architecture Demo"])
async def get_config_summary():
    """Return a sanitised summary of the runtime configuration."""
    return {
        "inference": {
            "backend": _config.get("inference", {}).get("llm_factory", {}).get("backend", "ollama"),
            "base_url": _config.get("inference", {}).get("llm_factory", {}).get("base_url", ""),
            "models": list((_config.get("inference", {}).get("llm_factory", {}).get("models", {}) or {}).keys()),
        },
        "messaging": {
            "backend": _config.get("messaging", {}).get("backend", "kafka"),
            "brokers": _config.get("messaging", {}).get("brokers", []),
            "topics": list((_config.get("messaging", {}).get("topics", {}) or {}).values()),
        },
        "persistence": _config.get("persistence", {}),
        "governance": {
            "enabled": _config.get("governance", {}).get("enabled", False),
        },
        "eoc": _config.get("eoc", {}),
        "monitoring": {
            "log_level": _config.get("monitoring", {}).get("log_level", "INFO"),
            "otel_enabled": _config.get("monitoring", {}).get("otel", {}).get("enabled", False),
        },
    }


@app.get("/api/eoc/graph", tags=["Architecture Demo"])
async def get_execution_graph(
    event_type: Optional[str] = Query(None, description="Event type filter for execution-path view"),
    view: Optional[str] = Query(None, description="Graph view: architecture | entities | fraud_network"),
):
    """
    Return nodes and edges for Cytoscape.js rendering.

    - view=architecture   K9-AIF component graph from Neo4j seed (fallback: static)
    - view=entities       Live Claimant/Claim/Policy/Document graph from Neo4j
    - view=fraud_network  Claimant→Claim→Policy traversal highlighting shared-policy risk
    - event_type=<type>   Execution-path graph for a specific scenario (backward compat)
    - (no params)         Same as view=architecture
    """
    if view == "entities":
        return _run_neo4j_view(_neo4j_entity_graph)
    if view == "fraud_network":
        return _run_neo4j_view(_neo4j_fraud_network)
    if event_type is None:
        return _get_full_architecture_graph()

    meta = _SCENARIO_META.get(event_type)
    if not meta:
        raise HTTPException(status_code=422, detail=f"Unknown event_type '{event_type}'")

    nodes: List[Dict[str, Any]] = [
        {"id": "event",  "label": f"Event\n{event_type}",  "type": "input"},
        {"id": "router", "label": "EOCRouter",              "type": "router"},
        {"id": "orch",   "label": "EOCOrchestrator",        "type": "orchestrator"},
        {"id": "loader", "label": "SquadLoader",            "type": "loader"},
        {"id": "squad",  "label": meta["squad"],            "type": "squad"},
    ]
    edges: List[Dict[str, Any]] = [
        {"id": "e0", "source": "event",  "target": "router", "label": "event_type"},
        {"id": "e1", "source": "router", "target": "orch",   "label": "dispatch"},
        {"id": "e2", "source": "orch",   "target": "loader", "label": "load_squad"},
        {"id": "e3", "source": "loader", "target": "squad",  "label": "init_agents"},
    ]

    prev_id = "squad"
    for i, name in enumerate(meta["agents"]):
        nid = f"agent_{i}"
        ntype = "governance" if name == "GuardAgent" else "audit" if name == "AuditAgent" else "agent"
        yaml_cfg = _AGENT_LOADER._by_class.get(name, {})
        nodes.append({"id": nid, "label": name, "type": ntype,
                      "model": yaml_cfg.get("model", "general"),
                      "pattern": yaml_cfg.get("pattern", "")})
        edges.append({"id": f"ea{i}", "source": prev_id, "target": nid, "label": f"step {i + 1}"})
        prev_id = nid

    for j, name in enumerate(meta.get("conditional_agents", [])):
        cid = f"cond_{j}"
        nodes.append({"id": cid, "label": name + "\n(if escalate)", "type": "conditional"})
        edges.append({"id": f"ec{j}", "source": prev_id, "target": cid,
                      "label": "escalate?", "conditional": True})
        prev_id = cid

    nodes.append({"id": "result", "label": "Result", "type": "output"})
    edges.append({"id": "eresult", "source": prev_id, "target": "result", "label": "complete"})

    return {"nodes": nodes, "edges": edges, "event_type": event_type, "squad": meta["squad"]}


def _get_neo4j_driver():
    from neo4j import GraphDatabase  # noqa: PLC0415
    neo4j_cfg = _config.get("neo4j", {})
    uri = os.getenv("NEO4J_URI") or neo4j_cfg.get("uri", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USER") or neo4j_cfg.get("user", "neo4j")
    password = os.getenv("NEO4J_PASSWORD") or neo4j_cfg.get("password", "")
    return GraphDatabase.driver(uri, auth=(username, password))


def _run_neo4j_view(fn) -> Dict[str, Any]:
    """Execute a Neo4j view function; return error payload on failure."""
    try:
        return fn()
    except Exception as exc:
        return {"nodes": [], "edges": [], "source": "error",
                "empty": True, "error": str(exc)}


# ── View: Architecture ────────────────────────────────────────────────────────

def _get_full_architecture_graph() -> Dict[str, Any]:
    try:
        return _neo4j_architecture_graph()
    except Exception:
        return _static_full_architecture_graph()


def _neo4j_architecture_graph() -> Dict[str, Any]:
    driver = _get_neo4j_driver()
    nodes_map: Dict[str, Any] = {}
    edges: List[Dict[str, Any]] = []
    edge_idx = 0

    with driver.session() as session:
        result = session.run("""
            MATCH (n:K9Component)
            OPTIONAL MATCH (n)-[r]->(m:K9Component)
            RETURN n, r, m
        """)
        for record in result:
            n = record["n"]
            nid = n.get("id")
            if nid and nid not in nodes_map:
                extra_labels = list(n.labels - {"K9Component"})
                ntype = extra_labels[0].lower() if extra_labels else "component"
                nodes_map[nid] = {
                    "id": nid, "label": n.get("label", nid), "type": ntype,
                    "model": n.get("model", ""), "pattern": n.get("pattern", ""),
                }
            m, r = record["m"], record["r"]
            if m and r:
                mid = m.get("id")
                if mid and mid not in nodes_map:
                    extra_labels = list(m.labels - {"K9Component"})
                    ntype = extra_labels[0].lower() if extra_labels else "component"
                    nodes_map[mid] = {
                        "id": mid, "label": m.get("label", mid), "type": ntype,
                        "model": m.get("model", ""), "pattern": m.get("pattern", ""),
                    }
                if nid and mid:
                    edges.append({
                        "id": f"e{edge_idx}", "source": nid, "target": mid,
                        "label": r.type.replace("_", " ").lower(),
                    })
                    edge_idx += 1

    driver.close()
    return {"nodes": list(nodes_map.values()), "edges": edges,
            "view": "architecture", "source": "neo4j", "empty": not nodes_map}


def _static_full_architecture_graph() -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = [{"id": "router", "label": "EOCRouter", "type": "router"}]
    edges: List[Dict[str, Any]] = []
    agent_ids: Dict[str, str] = {}
    edge_idx = 0

    for evt, meta in _SCENARIO_META.items():
        oid = f"orch_{evt}"
        nodes.append({"id": oid, "label": meta.get("orchestrator", evt), "type": "orchestrator"})
        edges.append({"id": f"e{edge_idx}", "source": "router", "target": oid,
                      "label": evt.replace("_", " ")})
        edge_idx += 1
        prev = oid
        for i, name in enumerate(meta.get("agents", [])):
            if name not in agent_ids:
                ntype = ("governance" if name == "GuardAgent"
                         else "audit" if name == "AuditAgent" else "agent")
                agent_ids[name] = name
                yaml_cfg = _AGENT_LOADER._by_class.get(name, {})
                nodes.append({"id": name, "label": name, "type": ntype,
                              "model": yaml_cfg.get("model", "general")})
            edges.append({"id": f"e{edge_idx}", "source": prev, "target": name,
                          "label": f"step {i + 1}"})
            edge_idx += 1
            prev = name

    return {"nodes": nodes, "edges": edges, "view": "architecture", "source": "static", "empty": False}


# ── View: Entities (live Claimant / Claim / Policy / Document) ────────────────

_ENTITY_LABELS = {"Claimant", "Claim", "Policy", "Document", "Alert"}
_ENTITY_KEY = {"Claimant": "claimant_id", "Claim": "claim_id",
               "Policy": "policy_id", "Document": "document_id", "Alert": "alert_id"}


def _entity_label(node) -> str:
    return next((l for l in node.labels if l in _ENTITY_LABELS), "entity")


def _entity_nid(node, label: str) -> str:
    key = _ENTITY_KEY.get(label)
    val = node.get(key) if key else None
    return f"{label.lower()}_{val}" if val else f"{label.lower()}_{id(node)}"


def _entity_display(node, label: str) -> str:
    if label == "Claimant":
        return node.get("claimant_id", "?")
    if label == "Claim":
        cid = node.get("claim_id", "")
        ctype = node.get("claim_type", "")
        return f"{cid}\n{ctype}" if ctype else cid or "claim"
    if label == "Policy":
        return node.get("policy_id", "?")
    if label == "Document":
        return node.get("document_id", node.get("filename", "doc"))
    if label == "Alert":
        return node.get("alert_id", "alert")
    return str(dict(node))[:30]


def _neo4j_entity_graph() -> Dict[str, Any]:
    driver = _get_neo4j_driver()
    nodes_map: Dict[str, Any] = {}
    edges: List[Dict[str, Any]] = []
    edge_idx = 0

    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE any(lbl IN labels(n) WHERE lbl IN ['Claimant','Claim','Policy','Document','Alert'])
            OPTIONAL MATCH (n)-[r]->(m)
            WHERE any(lbl IN labels(m) WHERE lbl IN ['Claimant','Claim','Policy','Document','Alert'])
            RETURN n, r, m
            LIMIT 300
        """)
        for record in result:
            n = record["n"]
            lbl = _entity_label(n)
            nid = _entity_nid(n, lbl)
            if nid not in nodes_map:
                nodes_map[nid] = {
                    "id": nid, "label": _entity_display(n, lbl), "type": lbl.lower(),
                    "amount": float(n.get("amount", n.get("amount_claimed", 0)) or 0),
                }
            m, r = record["m"], record["r"]
            if m and r:
                mlbl = _entity_label(m)
                mid = _entity_nid(m, mlbl)
                if mid not in nodes_map:
                    nodes_map[mid] = {
                        "id": mid, "label": _entity_display(m, mlbl), "type": mlbl.lower(),
                        "amount": float(m.get("amount", m.get("amount_claimed", 0)) or 0),
                    }
                edges.append({"id": f"e{edge_idx}", "source": nid, "target": mid,
                              "label": r.type.replace("_", " ")})
                edge_idx += 1

    driver.close()
    return {"nodes": list(nodes_map.values()), "edges": edges,
            "view": "entities", "source": "neo4j", "empty": not nodes_map}


# ── View: Fraud Network (Claimant → Claim → Policy traversal) ─────────────────

def _neo4j_fraud_network() -> Dict[str, Any]:
    driver = _get_neo4j_driver()
    nodes_map: Dict[str, Any] = {}
    edges: List[Dict[str, Any]] = []
    edge_idx = 0
    policy_claim_counts: Dict[str, int] = {}

    with driver.session() as session:
        result = session.run("""
            MATCH (c:Claimant)-[f:FILED]->(cl:Claim)
            OPTIONAL MATCH (cl)-[cb:COVERED_BY]->(p:Policy)
            RETURN c, f, cl, cb, p
            LIMIT 200
        """)
        for record in result:
            c, cl = record["c"], record["cl"]
            p, f, cb = record["p"], record["f"], record["cb"]

            cid  = f"claimant_{c.get('claimant_id','unk')}"
            clid = f"claim_{cl.get('claim_id','unk')}"

            if cid not in nodes_map:
                nodes_map[cid] = {"id": cid, "label": c.get("claimant_id", "?"),
                                  "type": "claimant"}
            if clid not in nodes_map:
                amount = float(cl.get("amount", cl.get("amount_claimed", 0)) or 0)
                nodes_map[clid] = {
                    "id": clid,
                    "label": f"{cl.get('claim_id','claim')}\n{cl.get('claim_type','')}".strip(),
                    "type": "claim", "amount": amount,
                    "status": cl.get("status", ""),
                }

            edges.append({"id": f"e{edge_idx}", "source": cid, "target": clid,
                          "label": "filed"})
            edge_idx += 1

            if p and cb:
                pid = f"policy_{p.get('policy_id','unk')}"
                if pid not in nodes_map:
                    nodes_map[pid] = {"id": pid, "label": p.get("policy_id", "?"),
                                      "type": "policy", "risk": "normal"}
                policy_claim_counts[pid] = policy_claim_counts.get(pid, 0) + 1
                edges.append({"id": f"e{edge_idx}", "source": clid, "target": pid,
                              "label": "covered by"})
                edge_idx += 1

    # Flag policies with multiple claims as high-risk
    for pid, count in policy_claim_counts.items():
        if pid in nodes_map:
            nodes_map[pid]["claim_count"] = count
            if count > 1:
                nodes_map[pid]["risk"] = "high"
                nodes_map[pid]["label"] = nodes_map[pid]["label"] + f"\n⚠ {count} claims"

    driver.close()
    return {"nodes": list(nodes_map.values()), "edges": edges,
            "view": "fraud_network", "source": "neo4j", "empty": not nodes_map}


# ============================================================
# Root redirect + static webui
# ============================================================

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the web UI."""
    return RedirectResponse(url="/webui/landing.html")


_WEBUI_DIR = Path(__file__).parent.parent / "webui"
if _WEBUI_DIR.is_dir():
    app.mount("/webui", StaticFiles(directory=str(_WEBUI_DIR), html=True), name="webui")
