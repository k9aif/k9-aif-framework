# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF  ACME HealthCare Orchestrator (SBB Root)
# Root orchestrator that dynamically delegates to sub-orchestrators.

import importlib
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_utils.config_loader import load_yaml


class AcmeOrchestrator(BaseOrchestrator):
    """
    AcmeOrchestrator
    ================
    Root orchestration controller for the ACME HealthCare SBB layer.

    Responsibilities
    ----------------
     Loads ACME's domain orchestrator registry from
      `examples/acme_health_insurance/config/orchestrators.yaml`.
     Dynamically imports and delegates control to the appropriate
      orchestrator class based on detected intent.
     Ensures isolation between orchestrators and centralizes monitoring.

    Attributes
    ----------
    layer : str
        Logical identifier for monitoring/logging ("SBB Orchestration Layer").
    registry : List[Dict[str, Any]]
        List of orchestrator definitions loaded from YAML.
    """

    layer = "SBB Orchestration Layer"

    # ------------------------------------------------------------------
    def __init__(self, config=None, monitor=None):
        """
        Initialize the ACME Orchestrator registry.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration dictionary for orchestrator setup.
        monitor : object, optional
            Monitoring instance for observability hooks.
        """
        super().__init__(config=config, monitor=monitor)
        self.registry = []
        try:
            self.registry = self._load_registry()
            self.logger.info(f"[{self.layer}]  Loaded {len(self.registry)} ACME orchestrators")
        except Exception as e:
            self.logger.error(f"[{self.layer}]  Failed to load orchestrators: {e}")
            self.registry = []

    # ------------------------------------------------------------------
    def _load_registry(self):
        """
        Load the ACME SBB orchestrator definitions from YAML.

        Returns
        -------
        List[Dict[str, Any]]
            List of orchestrator metadata entries.
        """
        return load_yaml("examples/acme_health_insurance/config/orchestrators.yaml").get("orchestrators", [])

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delegate orchestration execution to the proper sub-orchestrator.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input payload containing 'intent' and other contextual keys.

        Returns
        -------
        Dict[str, Any]
            Response from the delegated orchestrator.
        """
        intent = payload.get("intent", "")
        self.logger.info(f"[{self.layer}]  Handling intent={intent}")

        entry = next((o for o in self.registry if o.get("intent") == intent), None)
        if not entry:
            self.logger.warning(f"[{self.layer}]  No orchestrator found for intent={intent}")
            return {"reply": f"No ACME handler found for intent '{intent}'."}

        try:
            module = importlib.import_module(entry["module"])
            cls = getattr(module, entry["name"])
            orchestrator = cls(config=self.config, monitor=self.monitor)
            self.logger.info(f"[{self.layer}]  Delegating to {entry['name']} ({entry['module']})")

            # Execute the sub-orchestrator (supports async)
            result = await orchestrator.execute_flow(payload)
            self.publish_status("completed", {"intent": intent})
            return result

        except Exception as e:
            self.logger.error(f"[{self.layer}]  Delegation failed: {e}")
            self.publish_status("error", {"intent": intent, "error": str(e)})
            return {"reply": "ACME orchestration error."}