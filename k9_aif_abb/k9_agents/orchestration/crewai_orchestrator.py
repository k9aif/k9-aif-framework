# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_agents/orchestration/crew_orchestrator.py

"""
CrewAI Orchestrator Agent (SBB)
-------------------------------
Provides an orchestration layer for CrewAI-style multi-agent workflows
within the K9-AIF framework.

The CrewOrchestrator coordinates multiple domain-specific agents
(e.g., RetrievalAgent, GovernanceAgent, PersistenceAgent)
to execute a collaborative pipeline.
"""

from typing import Any, Dict, List
import logging

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_factories.agent_factory import AgentFactory


class CrewOrchestrator(BaseOrchestrator):
    """
    CrewOrchestrator - SBB
    ----------------------
    Demonstrates how K9-AIF can manage multi-agent flows
    (CrewAI-compatible orchestration).
    """

    layer = "Orchestration SBB"

    def __init__(self, config: Dict[str, Any] | None = None, monitor=None):
        super().__init__(name="CrewOrchestrator", config=config or {}, monitor=monitor)
        self.logger = logging.getLogger(self.layer)
        self.agents: List[Any] = []

    # ------------------------------------------------------------------
    def bootstrap_agents(self) -> None:
        """Initialize core CrewAI-style agents from config."""
        try:
            agent_defs = self.config.get("crew_agents", [])
            for adef in agent_defs:
                agent = AgentFactory.create(adef, monitor=self.monitor)
                if agent:
                    self.agents.append(agent)
                    self.logger.info(f"[{self.layer}] Bootstrapped {adef.get('name')}")
        except Exception as e:
            self.logger.error(f"[{self.layer}] Bootstrap failed: {e}")

    # ------------------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a complete CrewAI-style pipeline.
        Input payload is routed across agents sequentially.
        """
        self.logger.info(f"[{self.layer}] Starting Crew pipeline execution")
        result = payload.copy()
        for agent in self.agents:
            try:
                result = agent.execute(result)
                self.logger.info(f"[{self.layer}] Agent {agent.__class__.__name__} completed.")
            except Exception as e:
                self.logger.error(f"[{self.layer}] Agent {agent.__class__.__name__} failed: {e}")
                continue
        return result

    # ------------------------------------------------------------------
    def shutdown(self):
        """Cleanly terminate orchestrator and agents."""
        for agent in self.agents:
            if hasattr(agent, "close"):
                agent.close()
        self.logger.info(f"[{self.layer}] CrewOrchestrator shutdown complete.")