# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — squads package

"""
EOC Squads Package
==================

This package contains the Squad layer for the K9X Enterprise Insurance
Operations Center (EOC). The Squad layer is the runtime assembly point
where agents and orchestrators are bound together and exposed as a
named, callable unit.

Architecture
------------

The Squad layer follows the standard K9-AIF two-directory pattern::

    squads/
        src/      ← Python Squad class implementations (SBB)
        yaml/     ← Declarative YAML descriptors (loaded by SquadLoader)

Each Squad class is a thin wrapper — it holds agent references injected
at runtime by SquadLoader, and delegates all execution to its paired
Orchestrator. No business logic lives in squad classes.

Squad ↔ Orchestrator ↔ Event Mapping
--------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Squad
     - Orchestrator
     - Event Trigger
   * - ClaimsProcessingSquad
     - ClaimsProcessingOrchestrator
     - ClaimSubmitted
   * - DocumentIntelligenceSquad
     - DocumentIntelligenceOrchestrator
     - DocumentReceived
   * - RiskAssessmentSquad
     - RiskAssessmentOrchestrator
     - FraudSignalRaised
   * - PolicyManagementSquad
     - PolicyManagementOrchestrator
     - PolicyChangeRequested
   * - CatastropheResponseSquad
     - CatastropheResponseOrchestrator
     - CatastropheAlertIssued
   * - CustomerServiceSquad
     - CustomerServiceOrchestrator
     - CustomerInteractionLogged
   * - AuditComplianceSquad
     - AuditComplianceOrchestrator
     - AuditQueryReceived

Runtime Loading
---------------

Squads are loaded at boot time by ``SquadLoader`` using the YAML
descriptors in ``squads/yaml/``. The ``EOCBootstrap`` class in
``utils/bootstrap.py`` orchestrates this process::

    loader = SquadLoader(agent_registry, orchestrator_registry)
    squads = loader.load(squads_yaml_path)
"""

from examples.K9X_Enterprise_Insurance_OperationsCenter.squads.src import (
    ClaimsProcessingSquad,
    DocumentIntelligenceSquad,
    RiskAssessmentSquad,
    PolicyManagementSquad,
    CatastropheResponseSquad,
    CustomerServiceSquad,
    AuditComplianceSquad,
)

__all__ = [
    "ClaimsProcessingSquad",
    "DocumentIntelligenceSquad",
    "RiskAssessmentSquad",
    "PolicyManagementSquad",
    "CatastropheResponseSquad",
    "CustomerServiceSquad",
    "AuditComplianceSquad",
]
