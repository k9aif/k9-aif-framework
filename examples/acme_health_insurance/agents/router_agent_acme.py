# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

 # SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# ACME HealthCare RouterAgent (SBB)
# Domain-specific router that extends the ABB RouterAgent.

import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from k9_aif_abb.k9_agents.router.router_agent import RouterAgent


class RouterAgentACME(RouterAgent):
    """
    RouterAgentACME
    ===============
    Specialized router for the ACME HealthCare domain.

    Extends
    --------
    `RouterAgent` from the ABB layer.

    Responsibilities
    ----------------
     Loads the ACME-specific `orchestrators.yaml` registry.  
     Detects user intent from input payloads or queries.  
     Maps detected intents to registered orchestrator names.  
     Maintains full compliance with the K9-AIF ABBSBB layering model.

    Notes
    -----
    - No direct import of orchestrator classes to preserve isolation.
    - The `execute()` method is asynchronous and safe for CrewAI event loops.

    Attributes
    ----------
    layer : str
        Logical label for the router layer ("Router SBB").
    registry : Dict[str, str]
        In-memory mapping of intent keywords  orchestrator names.
    """

    layer = "Router SBB"

    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None):
        """
        Initialize the ACME RouterAgent and load its orchestrator registry.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration dictionary (injected from framework runtime).
        monitor : object, optional
            Optional monitoring hook implementing `record_event(event)`.
        """
        super().__init__(config=config, monitor=monitor)
        self.logger = logging.getLogger("RouterAgentACME")

        try:
            self.registry = self._load_acme_registry()
            print(f"[Router SBB]  Router registry initialized with {len(self.registry)} intents")
        except Exception as e:
            print(f"[Router SBB]  Failed to load ACME orchestrators: {e}")
            self.registry = {}

    # ------------------------------------------------------------------
    def _load_acme_registry(self) -> Dict[str, str]:
        """
        Load orchestrator intent mappings from ACME configuration.

        Returns
        -------
        Dict[str, str]
            Dictionary mapping intent keywords  orchestrator names.

        Notes
        -----
        Reads `examples/acme_health_insurance/config/orchestrators.yaml`.
        Example structure::

            orchestrators:
              - intent: claims_support
                name: ClaimsOrchestrator
              - intent: find_doctor
                name: ProviderOrchestrator
        """
        acme_path = Path("examples/acme_health_insurance/config/orchestrators.yaml")
        print(f"[Router SBB]  Loading orchestrator registry from {acme_path}")

        if not acme_path.exists():
            print(f"[Router SBB]  File not found: {acme_path}")
            return {}

        with open(acme_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            orchestrators = data.get("orchestrators", [])
            mapping = {
                o.get("intent"): o.get("name")
                for o in orchestrators
                if o.get("intent") and o.get("name")
            }

            for intent, name in mapping.items():
                print(f"[Router SBB]  Mapped ACME intent='{intent}'  '{name}'")

            return mapping

    # ------------------------------------------------------------------
    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect intent and map to an orchestrator within the ACME domain.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input message or document payload containing contextual text.

        Returns
        -------
        Dict[str, Any]
            Dictionary with resolved intent and mapped orchestrator name.
        """
        self.log(" ACME RouterAgent execution started")
        query = payload.get("message", "").lower()
        top_k = payload.get("top_k", 5)
        collection_name = payload.get("collection", "default")

        print(f"[Retriever SBB]  Searching collection={collection_name}, query={query}, top_k={top_k}")

        # --- Intent detection heuristic ---
        if any(k in query for k in ["plan", "benefit", "coverage"]):
            intent = "health_plan"
        elif any(k in query for k in ["doctor", "provider", "hospital"]):
            intent = "find_doctor"
        elif any(k in query for k in ["claim", "reimburse", "insurance"]):
            intent = "claims_support"
        else:
            intent = "fallback"

        orchestrator = self.registry.get(intent)
        if orchestrator:
            self.log(f" Routed ACME intent={intent}  {orchestrator}")
        else:
            self.log(f" No orchestrator found for intent={intent}")

        return {"intent": intent, "orchestrator": orchestrator}