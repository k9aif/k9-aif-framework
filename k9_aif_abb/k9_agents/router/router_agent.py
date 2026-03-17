# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - RouterAgent (ABB Core, Debug Instrumented)

import logging
import yaml
from typing import Dict, Any, Optional
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class RouterAgent(BaseAgent):
    layer = "Router ABB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None):
        super().__init__(config=config, name="RouterAgent", monitor=monitor)
        self.logger = logging.getLogger("RouterAgent")

        try:
            raw_registry = config.get("orchestrators", {}) or self._load_registry()
            print(f"[Router ABB]  Raw orchestrator registry type: {type(raw_registry)}")
            self.registry = self._normalize_registry(raw_registry)

            print(f"[Router ABB] [OK] Loaded {len(self.registry)} orchestrators:")
            for intent, orch in self.registry.items():
                print(f"    -> intent='{intent}' -> orchestrator='{orch}'")

            self.log(f"[OK] Router registry initialized with {len(self.registry)} intents")
        except Exception as e:
            self.registry = {}
            self.log(f"[WARN] Failed to load orchestrator registry: {e}")

    # ------------------------------------------------------------------
    def _load_registry(self) -> Dict[str, Any]:
        """Load orchestrators.yaml if not provided by config."""
        try:
            path = "k9_aif_abb/config/orchestrators.yaml"
            print(f"[Router ABB]  Loading orchestrator registry from {path}")
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                print(f"[Router ABB] [OK] File read successfully: {len(data.get('orchestrators', []))} entries found")
                return data.get("orchestrators", [])
        except Exception as e:
            print(f"[Router ABB] [ERROR] Failed to read orchestrators.yaml: {e}")
            return {}

    # ------------------------------------------------------------------
    def _normalize_registry(self, raw: Any) -> Dict[str, str]:
        """Convert orchestrator list -> dict: intent -> name."""
        mapping = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                mapping[k] = v.get("name", "")
        elif isinstance(raw, list):
            for entry in raw:
                intent = entry.get("intent")
                name = entry.get("name")
                if intent and name:
                    mapping[intent] = name
                    print(f"[Router ABB] [INFO] Mapped intent='{intent}' -> '{name}'")
                else:
                    print(f"[Router ABB] [WARN] Skipping invalid entry: {entry}")
        else:
            print(f"[Router ABB] [WARN] Unexpected registry format: {type(raw)}")
        return mapping

    # ------------------------------------------------------------------
    def route(self, intent: str) -> Optional[str]:
        orch_name = self.registry.get(intent)
        if orch_name:
            self.log(f" Routed intent={intent} -> {orch_name}")
        else:
            self.log(f"[WARN] No orchestrator found for intent={intent}")
        return orch_name

    # ------------------------------------------------------------------
    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.log(" RouterAgent execution started (ABB mode)")
        intent = payload.get("intent", "unknown")
        orchestrator = self.route(intent)
        print(f"[Router ABB] [INFO] Executed route: intent='{intent}', orchestrator='{orchestrator}'")

        return {"intent": intent, "orchestrator": orchestrator}