# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — squads/src package

"""
EOC Squad Implementations (SBB)
================================

Seven thin runtime Squad classes — one per business domain event. Each Squad:

- Holds references to agent instances (injected at runtime by SquadLoader)
- Delegates all execution to its paired Orchestrator
- Contains zero business logic

Squads and their event triggers
--------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Squad Class
     - Event Trigger
     - Flow Summary
   * - ClaimsProcessingSquad
     - ClaimSubmitted
     - Triage → Adjudicate → Guard → Audit → Escalate?
   * - DocumentIntelligenceSquad
     - DocumentReceived
     - Extract → Guard → GraphSync → Audit
   * - RiskAssessmentSquad
     - FraudSignalRaised
     - Fraud → Guard → Audit → Escalate?
   * - PolicyManagementSquad
     - PolicyChangeRequested
     - Guard → Audit
   * - CatastropheResponseSquad
     - CatastropheAlertIssued
     - Exposure → Audit
   * - CustomerServiceSquad
     - CustomerInteractionLogged
     - Intent → Guard → Audit → Escalate?
   * - AuditComplianceSquad
     - AuditQueryReceived
     - AuditQuery → Compliance Report
"""

from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.claims_processing_squad import ClaimsProcessingSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.document_intelligence_squad import DocumentIntelligenceSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.risk_assessment_squad import RiskAssessmentSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.policy_management_squad import PolicyManagementSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.catastrophe_response_squad import CatastropheResponseSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.customer_service_squad import CustomerServiceSquad
from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src.audit_compliance_squad import AuditComplianceSquad

__all__ = [
    "ClaimsProcessingSquad",
    "DocumentIntelligenceSquad",
    "RiskAssessmentSquad",
    "PolicyManagementSquad",
    "CatastropheResponseSquad",
    "CustomerServiceSquad",
    "AuditComplianceSquad",
]
