# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

from typing import Any, Dict
import logging
from pathlib import Path

from k9_aif_abb.k9_utils.config_loader import load_app_config
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_orchestrators.registry.orchestrator_registry import OrchestratorRegistry
from k9_aif_abb.k9_squad.squad_loader import SquadLoader

from examples.acme_support_center.utils.systems_check import run_system_checks
from examples.acme_support_center.agents.src.triage_agent import TriageAgent
from examples.acme_support_center.agents.src.knowledge_agent import KnowledgeAgent
from examples.acme_support_center.agents.src.resolution_agent import ResolutionAgent
from examples.acme_support_center.agents.src.quality_agent import QualityAgent
from examples.acme_support_center.orchestrators.support_orchestrator import SupportOrchestrator


log = logging.getLogger(__name__)


class ACMESupportBootstrap:
    def __init__(self, app_name: str = "acme_support_center") -> None:
        self.app_name = app_name
        self.config: Dict[str, Any] = {}
        self.squads: Dict[str, Any] = {}
        self.orchestrators: Dict[str, Any] = {}

    def initialize(self) -> None:
        log.info("Initializing %s ...", self.app_name)

        root_dir = Path(__file__).resolve().parents[3]
        sbb_config_path = root_dir / "examples" / self.app_name / "config" / "config.yaml"
        squads_path = root_dir / "examples" / self.app_name / "config" / "squads.yaml"

        self.config = load_app_config(
            app_name=self.app_name,
            sbb_config=sbb_config_path,
        )

        ok = run_system_checks(self.config)
        if not ok:
            raise RuntimeError("System checks failed")

        agent_registry = AgentRegistry()

        agent_registry.register(
            "TriageAgent",
            lambda: TriageAgent(config=self.config)
        )

        agent_registry.register(
            "KnowledgeAgent",
            lambda: KnowledgeAgent(config=self.config)
        )

        agent_registry.register(
            "ResolutionAgent",
            lambda: ResolutionAgent(config=self.config)
        )

        agent_registry.register(
            "QualityAgent",
            lambda: QualityAgent(config=self.config)
        )

        orchestrator_registry = OrchestratorRegistry()
        orchestrator_registry.register("SupportOrchestrator", SupportOrchestrator)
        orchestrator_registry.register("support_orchestrator", SupportOrchestrator)

        loader = SquadLoader(agent_registry, orchestrator_registry)
        self.squads = loader.load(str(squads_path))

        self.orchestrators["support_orchestrator"] = SupportOrchestrator(
            name="support_orchestrator",
            config=self.config,
        )

        log.info(
            "Bootstrap complete | squads=%s | orchestrators=%s",
            list(self.squads.keys()),
            list(self.orchestrators.keys()),
        )

    def get_orchestrator(self, name: str):
        if name not in self.orchestrators:
            raise ValueError(f"Orchestrator '{name}' not found")
        return self.orchestrators[name]