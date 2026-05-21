# SPDX-License-Identifier: Apache-2.0

"""
K9-AIF EOC — agents/src
========================

Concrete SBB agent implementations.
Each agent is also described by a corresponding YAML file in ``agents/yaml/``
which declares its name, role, goal, instructions, model assignment, and tools.

At runtime, :class:`~...utils.bootstrap.EOCBootstrap` uses
``AgentRegistry`` to register all agents and ``SquadLoader`` to assemble squads
from ``squads/yaml/``. Agents are loaded lazily from their source classes here.

Exported Agents
---------------
- :class:`ClaimsTriageAgent`
- :class:`AdjudicationAgent`
- :class:`GuardAgent`
- :class:`EscalationAgent`
- :class:`AuditAgent`
- :class:`DocumentExtractorAgent`
- :class:`FraudDetectionAgent`
- :class:`GraphSyncAgent`
"""

from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.claims_triage_agent import ClaimsTriageAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.adjudication_agent import AdjudicationAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.guard_agent import GuardAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.escalation_agent import EscalationAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.audit_agent import AuditAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.document_extractor_agent import DocumentExtractorAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.fraud_detection_agent import FraudDetectionAgent
from examples.K9X_Enterprise_Insurance_OperationsCenter.agents.src.graph_sync_agent import GraphSyncAgent

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
