# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — HealthMonitorAgent (SBB)
# Checks Ollama, MCP, and Messaging health, publishes live status.

import requests
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class HealthMonitorAgent(BaseAgent):
    """SBB Agent that performs live system health checks."""

    layer = "HealthMonitor SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.ollama_url = (
            config.get("inference", {})
            .get("llm_factory", {})
            .get("base_url", "http://localhost:11434")
        )
        self.mcp_url = (
            config.get("mcp_servers", {}).get("url", "http://localhost:8001")
        )
        self.kafka_broker = (
            config.get("messaging", {}).get("brokers", ["localhost:9092"])[0]
        )

    # --------------------------------------------------------------
    def _ping(self, url: str, endpoint: str = "", timeout: int = 3) -> bool:
        """HTTP GET ping helper."""
        try:
            r = requests.get(f"{url}{endpoint}", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    # --------------------------------------------------------------
    async def execute(self, payload=None):
        """Perform live health checks and publish to console."""
        self.log(f"[{self.layer}] 🔍 Running system health checks...")

        ollama_ok = self._ping(self.ollama_url, "/api/tags")
        mcp_ok = self._ping(self.mcp_url, "/health")

        status = {
            "ollama": "green" if ollama_ok else "red",
            "mcp": "green" if mcp_ok else "red",
            "status": "healthy" if (ollama_ok and mcp_ok) else "degraded",
        }

        # --- Publish event to console
        if getattr(self, "messaging", None):
            try:
                self.messaging.publish({
                    "event_type": "system_health",
                    "layer": self.layer,
                    "status": status,
                })
                self.log(f"[{self.layer}] 🛰️ Published system_health event.")
            except Exception as e:
                self.log(f"[{self.layer}] ⚠️ Publish failed: {e}")

        return status