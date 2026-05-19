# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/bootstrap.py (SBB)

from __future__ import annotations

import threading
from typing import Any, Dict, List
import logging
from pathlib import Path

from k9_aif_abb.k9_utils.config_loader import load_app_config
from k9_aif_abb.k9_core.logging.log_setup import setup_logging

from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.systems_check import run_system_checks
from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router import EOCRouter

# Squad orchestrators — each self-bootstraps via SquadLoader
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.claims_processing_orchestrator import ClaimsProcessingOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.document_intelligence_orchestrator import DocumentIntelligenceOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.risk_assessment_orchestrator import RiskAssessmentOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.policy_management_orchestrator import PolicyManagementOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.catastrophe_response_orchestrator import CatastropheResponseOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.customer_service_orchestrator import CustomerServiceOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.audit_compliance_orchestrator import AuditComplianceOrchestrator


log = logging.getLogger(__name__)

_APP_NAME = "K9X_Enterprise_Insurance_OperationsCenter"


class EOCBootstrap:
    """
    Bootstrap controller for the K9X Enterprise Insurance Operations Center.

    Architecture
    ------------
    ::

        EOCRouter
            ↓  publishes to Kafka topic by event_type
        Kafka topics (eoc-claims, eoc-documents, eoc-fraud, ...)
            ↓  each topic consumed by its squad orchestrator
        Squad Orchestrators  ← each reads config, uses SquadLoader to load squad + agents
            ↓  agents run sequentially with full context
        Agents (ClaimsTriageAgent, AdjudicationAgent, GuardAgent, ...)

    Responsibilities
    ----------------
    1. Load application config (``config/config.yaml``)
    2. Run pre-flight system checks
    3. Instantiate the ``EOCRouter`` (event router, publishes to Kafka)
    4. Instantiate all 7 squad orchestrators
    5. Start each orchestrator in its own thread (each calls ``start()``
       which loads its squad via SquadLoader then blocks on Kafka subscribe)

    Usage::

        bootstrap = EOCBootstrap()
        bootstrap.initialize()
        router = bootstrap.router   # use in FastAPI endpoints to route events
    """

    def __init__(self, app_name: str = _APP_NAME) -> None:
        self.app_name = app_name
        self.config: Dict[str, Any] = {}
        self.router: EOCRouter | None = None
        self.orchestrators: Dict[str, Any] = {}
        self._threads: List[threading.Thread] = []

    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """
        Full bootstrap sequence.

        Raises:
            RuntimeError: If system checks fail.
        """
        root_dir = Path(__file__).resolve().parents[3]
        sbb_config_path = root_dir / "examples" / self.app_name / "config" / "config.yaml"
        squads_yaml_path = str(
            root_dir / "examples" / self.app_name / "config" / "squads.yaml"
        )

        # 1. Load config
        self.config = load_app_config(
            app_name=self.app_name,
            sbb_config=sbb_config_path,
        )

        setup_logging(app_name=self.app_name, app_config=self.config)
        log.info("=== K9X EOC Bootstrap starting ===")

        # 2. Pre-flight checks
        if not run_system_checks(self.config):
            raise RuntimeError("EOC system checks failed — aborting startup")

        # 3. EOCRouter (event router — publishes to Kafka topics by event_type)
        self.router = EOCRouter(config=self.config)

        # 4. Squad orchestrators — each self-bootstraps with SquadLoader
        self.orchestrators = {
            "ClaimsProcessingOrchestrator":    ClaimsProcessingOrchestrator(config=self.config),
            "DocumentIntelligenceOrchestrator": DocumentIntelligenceOrchestrator(config=self.config),
            "RiskAssessmentOrchestrator":      RiskAssessmentOrchestrator(config=self.config),
            "PolicyManagementOrchestrator":    PolicyManagementOrchestrator(config=self.config),
            "CatastropheResponseOrchestrator": CatastropheResponseOrchestrator(config=self.config),
            "CustomerServiceOrchestrator":     CustomerServiceOrchestrator(config=self.config),
            "AuditComplianceOrchestrator":     AuditComplianceOrchestrator(config=self.config),
        }

        # 5. Start each orchestrator in its own daemon thread
        #    Each orchestrator calls start(squads_yaml_path) which:
        #      a) uses SquadLoader to load its squad + agents
        #      b) subscribes to its Kafka topic (blocking)
        for name, orch in self.orchestrators.items():
            t = threading.Thread(
                target=orch.start,
                args=(squads_yaml_path,),
                name=name,
                daemon=True,
            )
            t.start()
            self._threads.append(t)
            log.info("Started orchestrator thread: %s", name)

        log.info(
            "=== EOC Bootstrap complete | router=ready | orchestrators=%d running ===",
            len(self.orchestrators),
        )

    # ------------------------------------------------------------------
    def get_router(self) -> EOCRouter:
        """
        Return the EOCRouter for use in FastAPI endpoints.

        Raises:
            RuntimeError: If bootstrap has not been called yet.
        """
        if self.router is None:
            raise RuntimeError("EOCBootstrap.initialize() has not been called")
        return self.router

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Gracefully shut down the router and stop event buses."""
        if self.router:
            self.router.close()
        log.info("=== EOC Bootstrap shutdown complete ===")
