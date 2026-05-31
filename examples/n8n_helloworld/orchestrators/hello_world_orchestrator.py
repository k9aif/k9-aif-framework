# SPDX-License-Identifier: Apache-2.0
# K9-AIF n8n Hello World — HelloWorldOrchestrator (SBB)

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

log = logging.getLogger(__name__)


class HelloWorldOrchestrator(BaseOrchestrator):

    layer = "n8n_helloworld HelloWorldOrchestrator SBB"

    def __init__(self, squad, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.squad = squad

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        log.info("[%s] Running squad for event: %s", self.layer, payload)
        result = self.squad.run(dict(payload))
        self.publish_status("completed", {"type": "HelloWorldFlowCompleted", "result": result.get("hello", {})})
        return result

    def run(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return self.execute_flow(event)
