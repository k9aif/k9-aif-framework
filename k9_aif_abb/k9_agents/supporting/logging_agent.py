# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_agents/logging/logging_agent.py

from typing import Dict, Any
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class LoggingAgent(BaseAgent):
    """
    K9-AIF LoggingAgent
    -------------------
    ABB-level agent for framework-wide logging.
    Used primarily in orchestrator chains or smoke tests
    to trace payloads as they traverse the pipeline.

    Responsibilities:
    - Log incoming requests
    - Optionally emit monitoring events
    - Return payload unchanged (pass-through)
    """

    layer = "Logging ABB"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config or {}, name="LoggingAgent")
        self.name = self.config.get("logging", {}).get("name", self.name)
        self.log(f"[{self.layer}] Initialized '{self.name}'")

    def execute(self, request: dict) -> dict:
        """Log and return the incoming request (no mutation)."""
        self.log(f"[{self.layer}] {self.name} received: {request}", level="INFO")

        # Example: future monitoring hook
        if hasattr(self, "monitor") and self.monitor:
            try:
                self.monitor.observe("logging_event", {"agent": self.name})
            except Exception:
                self.log(f"[{self.layer}] monitor.observe failed", "WARN")

        return request