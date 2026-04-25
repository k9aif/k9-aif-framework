# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - Base Orchestrator
# Abstract orchestrator foundation for coordinating multiple agents.

import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance


class BaseOrchestrator(ABC):
    """
    BaseOrchestrator
    =================
    Abstract base class for all orchestrators in the K9-AIF framework.
    """

    layer: str = "Orchestrator Base"

    # ------------------------------------------------------------------
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
        message_bus=None,
        governance=None,
    ):
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        self.governance = governance or NoopGovernance()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    # ------------------------------------------------------------------
    @abstractmethod
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement execute_flow()")

    # ------------------------------------------------------------------
    def publish_status(self, status: str, context: Dict[str, Any]):
        event = {"status": status, **context}
        if self.message_bus:
            self.message_bus.publish(event)
        if self.monitor:
            self.monitor.record_event(event)
        self.logger.info(f"[{self.layer}] Status event: {event}")

    # ------------------------------------------------------------------
    async def apply_pre_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        result = self.governance.pre_process(
            payload,
            ctx or self._governance_context(),
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    # ------------------------------------------------------------------
    async def apply_post_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        result = self.governance.post_process(
            payload,
            ctx or self._governance_context(),
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    # ------------------------------------------------------------------
    def _governance_context(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "component": self.__class__.__name__,
            "component_type": "orchestrator",
        }