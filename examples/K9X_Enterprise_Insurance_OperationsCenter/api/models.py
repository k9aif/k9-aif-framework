# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — API Pydantic Models

"""
Pydantic request and response models for the EOC FastAPI layer.

All models include OpenAPI ``Field`` descriptions for auto-generated
API documentation (accessible at /docs and /redoc).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# ============================================================
# Event Envelope
# ============================================================

class EOCEvent(BaseModel):
    """Base envelope for all enterprise events submitted to the EOC."""

    event_type: str = Field(
        ...,
        description="Event taxonomy type: claim_submitted | document_received | "
                    "fraud_signal_raised | policy_change_requested | "
                    "catastrophe_alert_issued | customer_interaction_logged | "
                    "audit_query_received",
        examples=["claim_submitted"],
    )
    event_id: Optional[str] = Field(
        default_factory=lambda: f"EVT-{uuid.uuid4().hex[:8].upper()}",
        description="Unique event identifier. Auto-generated if not provided.",
    )
    correlation_id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Trace identifier propagated across all agents in the flow.",
    )

    class Config:
        extra = "allow"


class ClaimSubmittedEvent(EOCEvent):
    """Typed payload for ClaimSubmitted events."""

    event_type: str = "claim_submitted"
    claim_id: Optional[str] = Field(None, description="Unique claim identifier")
    claimant_id: str = Field(..., description="Claimant identifier")
    policy_id: str = Field(..., description="Active policy identifier")
    claim_type: str = Field(..., description="Type of claim (property_damage, bodily_injury, etc.)")
    amount_claimed: float = Field(..., ge=0, le=1_000_000_000, description="Amount claimed in USD (max $1B — amounts above this are rejected at the API boundary and require manual submission)")
    notes: Optional[str] = Field(None, description="Free-text claim description")
    is_repeat_claimant: Optional[bool] = Field(False, description="True if claimant has prior claims")


class DocumentReceivedEvent(EOCEvent):
    """Typed payload for DocumentReceived events."""

    event_type: str = "document_received"
    document_id: Optional[str] = Field(None, description="Document identifier")
    claim_id: Optional[str] = Field(None, description="Associated claim ID")
    claimant_id: Optional[str] = Field(None, description="Document owner claimant ID")
    filename: str = Field(..., description="Original filename")
    file_type: Optional[str] = Field(None, description="MIME type or extension")
    raw_text: Optional[str] = Field(None, description="Pre-extracted text content")
    file_path: Optional[str] = Field(None, description="Path to file for OCR processing")


class FraudSignalEvent(EOCEvent):
    """Typed payload for FraudSignalRaised events."""

    event_type: str = "fraud_signal_raised"
    alert_id: Optional[str] = Field(None, description="Alert identifier")
    alert_source: str = Field(..., description="Source system that raised the signal")
    claimant_id: Optional[str] = Field(None, description="Claimant under review")
    claim_id: Optional[str] = Field(None, description="Related claim if applicable")
    description: str = Field(..., description="Description of the fraud signal")
    amount_claimed: Optional[float] = Field(0.0, description="Related claim amount if applicable")
    severity: Optional[str] = Field("medium", description="Signal severity: low | medium | high | critical")


class PolicyChangeEvent(EOCEvent):
    """Typed payload for PolicyChangeRequested events."""

    event_type: str = "policy_change_requested"
    policy_id: str = Field(..., description="Policy being modified")
    claimant_id: Optional[str] = Field(None, description="Policy holder")
    change_type: str = Field(..., description="Type of change: endorsement | cancellation | modification")
    change_description: str = Field(..., description="Description of the requested change")
    notes: Optional[str] = Field(None, description="Additional context")


class CatastropheAlertEvent(EOCEvent):
    """Typed payload for CatastropheAlertIssued events."""

    event_type: str = "catastrophe_alert_issued"
    alert_id: Optional[str] = Field(None, description="Catastrophe alert identifier")
    alert_description: str = Field(..., description="Description of the catastrophe event")
    estimated_exposure: Optional[float] = Field(0.0, description="Estimated total exposure in USD")
    affected_regions: Optional[List[str]] = Field(default_factory=list, description="Affected geographic regions")
    severity: Optional[str] = Field("high", description="Alert severity")


class CustomerInteractionEvent(EOCEvent):
    """Typed payload for CustomerInteractionLogged events."""

    event_type: str = "customer_interaction_logged"
    interaction_id: Optional[str] = Field(None, description="Interaction identifier")
    customer_id: str = Field(..., description="Customer / claimant identifier")
    policy_id: Optional[str] = Field(None, description="Related policy")
    interaction_type: str = Field(..., description="Type: inquiry | complaint | claim_status | coverage_question")
    customer_message: str = Field(..., description="Customer message or query content")
    channel: Optional[str] = Field("portal", description="Interaction channel: portal | phone | chat | email")


# ============================================================
# Query Models
# ============================================================

class AuditQueryRequest(BaseModel):
    """Query parameters for audit trail retrieval."""

    query_correlation_id: Optional[str] = Field(None, description="Filter by correlation ID")
    query_event_id: Optional[str] = Field(None, description="Filter by event ID")
    query_agent_name: Optional[str] = Field(None, description="Filter by agent name")
    query_event_type: Optional[str] = Field(None, description="Filter by event type")
    limit: int = Field(100, ge=1, le=1000, description="Maximum number of records to return")


class EscalationResolveRequest(BaseModel):
    """Payload for resolving a HITL escalation ticket."""

    operator_id: str = Field(..., description="ID of the human operator resolving the ticket")
    resolution: str = Field(..., description="Resolution decision: approve | deny | partial | defer")
    resolution_notes: Optional[str] = Field(None, description="Notes from the operator")


# ============================================================
# Response Models
# ============================================================

class EOCEventResponse(BaseModel):
    """Standard API response envelope for all event submissions."""

    status: str = Field(..., description="Processing status: completed | error | queued")
    event_id: str = Field(..., description="Event identifier")
    correlation_id: str = Field(..., description="Trace correlation ID")
    squad_id: Optional[str] = Field(None, description="Squad that handled this event")
    final_decision: Optional[str] = Field(None, description="Final disposition from the squad")
    confidence: Optional[float] = Field(None, description="Confidence score (0.0–1.0)")
    escalated: Optional[bool] = Field(None, description="True if event was escalated to HITL")
    ticket_id: Optional[str] = Field(None, description="Escalation ticket ID if escalated")
    audit_id: Optional[str] = Field(None, description="Audit record ID for this event")
    details: Optional[Dict[str, Any]] = Field(None, description="Full pipeline results")


class HealthResponse(BaseModel):
    """System health check response."""

    status: str
    service: str = "K9-AIF EOC"
    version: str = "0.1.0"
    components: Dict[str, str]


# ============================================================
# Architecture Demo Models
# ============================================================

class ScenarioRunRequest(BaseModel):
    """Request to execute a named scenario through the K9-AIF pipeline."""
    event_type: str = Field(..., description="One of the seven EOC event types")
    payload: Optional[Dict[str, Any]] = Field(None, description="Event payload; defaults to built-in sample if omitted")


class TraceStep(BaseModel):
    """A single step in the runtime execution trace — includes full agent transparency fields."""
    step: int
    component: str = Field(..., description="Class or layer name (EOCRouter, ClaimsTriageAgent, …)")
    layer: str = Field(..., description="router | orchestrator | squad | agent | governance | audit | escalation | result")
    status: str = Field(..., description="ok | warn | error")
    message: str
    final: bool = False
    # Agent transparency fields (populated for agent/governance steps)
    agent_yaml: Optional[Dict[str, Any]] = Field(None, description="Full agent YAML config: role, goal, instructions, pattern, governance")
    model_routing: Optional[Dict[str, Any]] = Field(None, description="Model selected, why, cost/latency/governance rationale")
    governance_detail: Optional[Dict[str, Any]] = Field(None, description="Pre/post guard gates, confidence threshold, PII fields")
    latency_ms: Optional[int] = Field(None, description="Estimated execution latency in milliseconds")
    tools: Optional[List[str]] = Field(None, description="Tool calls available to this agent")
    agent_result: Optional[Dict[str, Any]] = Field(None, description="Raw agent output from the pipeline result")


class ScenarioRunResponse(BaseModel):
    """Full pipeline result returned by POST /api/eoc/run."""
    event_type: str
    event_id: str
    correlation_id: str
    squad_id: Optional[str] = None
    trace: List[TraceStep]
    result: Dict[str, Any]
    error: Optional[str] = None
