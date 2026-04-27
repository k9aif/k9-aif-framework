# SPDX-License-Identifier: Apache-2.0

from typing import Dict, Any

from k9_aif_abb.k9_core.router.base_router import BaseRouter


class DemoRouter(BaseRouter):
    """
    Demo router showcasing Zero Trust enforcement at routing layer.
    """

    layer = "Demo Router"

    async def route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("[Router] Received payload")

        # ------------------------------------------------------------
        # Step 1: Normalize
        # ------------------------------------------------------------
        payload = self.normalize(payload)

        # ------------------------------------------------------------
        # Step 2: Pre-governance
        # ------------------------------------------------------------
        payload = await self.apply_pre_governance(payload)

        # ------------------------------------------------------------
        # Step 3: Zero Trust (Router-level)
        # ------------------------------------------------------------
        zt = self.apply_zero_trust(payload)

        if not zt["allowed"]:
            self.logger.warning("[Router] Request denied by Zero Trust")
            return {
                "status": "DENIED_AT_ROUTER",
                "zero_trust": zt,
            }

        payload = zt["payload"]

        # ------------------------------------------------------------
        # Step 4: Intent routing
        # ------------------------------------------------------------
        intent = payload.get("intent", "default")

        orchestrator = self.registry.get(intent)

        if not orchestrator:
            return {
                "status": "NO_ROUTE",
                "intent": intent,
            }

        result = await orchestrator.execute_flow(payload)

        # ------------------------------------------------------------
        # Step 5: Post-governance
        # ------------------------------------------------------------
        result = await self.apply_post_governance(result)

        return result