# SPDX-License-Identifier: Apache-2.0

from typing import Dict, Any

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator


class DemoClaimsOrchestrator(BaseOrchestrator):
    """
    Demo orchestrator to showcase Zero Trust execution behavior.
    """

    layer = "Demo Claims Orchestrator"

    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.publish_status("STARTED", {"stage": "demo_flow"})

        # ------------------------------------------------------------
        # Step 1: Pre-governance
        # ------------------------------------------------------------
        payload = await self.apply_pre_governance(payload)

        # ------------------------------------------------------------
        # Step 2: Zero Trust Enforcement (NEW)
        # ------------------------------------------------------------
        zt = self.apply_zero_trust(payload)

        if not zt["allowed"]:
            self.publish_status("DENIED", {"reason": zt["reason"]})
            return {
                "status": "DENIED",
                "zero_trust": zt,
            }

        payload = zt["payload"]

        # ------------------------------------------------------------
        # Step 3: Execute business logic
        # ------------------------------------------------------------
        result = {
            "message": "Claims workflow executed successfully",
            "processed_payload": payload,
        }

        # ------------------------------------------------------------
        # Step 4: Post-governance
        # ------------------------------------------------------------
        result = await self.apply_post_governance(result)

        self.publish_status("COMPLETED", {"stage": "demo_flow"})

        return {
            "status": "COMPLETED",
            "zero_trust": zt,
            "result": result,
        }