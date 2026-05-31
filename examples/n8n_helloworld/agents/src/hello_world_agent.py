# SPDX-License-Identifier: Apache-2.0
# K9-AIF n8n Hello World — HelloWorldAgent (SBB)

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent


class HelloWorldAgent(BaseAgent):

    layer = "n8n_helloworld HelloWorldAgent SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        caller = payload.get("caller", "n8n")
        self.logger.info("[%s] Received payload from: %s", self.layer, caller)

        self.publish_event({"type": "HelloWorldCompleted", "agent": "HelloWorldAgent"})

        return {
            "message": f"Hello World from K9-AIF Agent! 👋 Triggered by: {caller}",
            "caller": caller,
            "agent": "HelloWorldAgent",
            "status": "success",
            "pipeline": "Router → Orchestrator → Squad → Agent",
        }
