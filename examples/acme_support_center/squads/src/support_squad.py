from __future__ import annotations

from typing import Any, Dict, Optional
import logging


log = logging.getLogger(__name__)


class SupportSquad:
    """
    Thin runtime Squad (SBB)

    - Holds agent instances
    - Delegates execution to orchestrator
    - Does NOT contain business logic
    """

    def __init__(
        self,
        name: str,
        agents: Dict[str, Any],
        orchestrator: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.agents = agents
        self.orchestrator = orchestrator
        self.config = config or {}

        log.info("Initialized squad: %s", self.name)

    def run(self, request: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Entry point for squad execution.
        Delegates to orchestrator.
        """
        context = context or {}

        log.info("Squad %s received request", self.name)

        return self.orchestrator.run(
            request=request,
            agents=self.agents,
            context=context,
        )