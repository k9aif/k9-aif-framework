# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — squads package

"""
EOC Squads Package
==================

The Squad layer of the K9X Enterprise Insurance Operations Center (EOC).

A squad is configuration: ``config/squads.yaml`` names each squad's agents and
its ``flow:``; the framework's ``BaseSquad`` runs the flow. The squad layer
(``squad_layer.py``: ``SquadLoader.from_agents``) builds the agents each squad's
YAML names, through the agent YAML's ``class:`` + ``module:``.

An orchestrator knows only squads (three-layer decoupling, k9_inspect
K9-DEC-002): it loads its squad by YAML file and squad id through the squad
layer, built once at the entry point (``utils/bootstrap.py``,
``orchestrators/eoc_orchestrator.py``). A squad does not know which
orchestrator calls it. If a squad's agents change, no orchestrator changes.

``squads/src`` holds one named ``BaseSquad`` subclass per EOC squad, kept for
registry and type-checking purposes; the loader builds ``BaseSquad`` itself.
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
