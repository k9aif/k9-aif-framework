# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - Base Router
# Central abstract router that directs payloads to orchestrators by intent.

import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance


class BaseRouter(ABC):
    """
    BaseRouter
    ==========
    Abstract foundation for routing logic in the K9-AIF framework.

    Adds optional policy-governance hooks through a governance object
    implementing pre_process(payload, ctx) and post_process(payload, ctx).
    """

    layer: str = "Router Base"

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
        self.registry: Dict[str, Any] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    def register_orchestrator(self, intent: str, orchestrator: Any):
        self.registry[intent] = orchestrator
        self.logger.info(f"[{self.layer}] Registered orchestrator for intent: {intent}")

    @abstractmethod
    def route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement route()")

    def normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload

    async def apply_pre_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply governance before routing.
        """
        result = self.governance.pre_process(payload, ctx or self._governance_context())
        if inspect.isawaitable(result):
            result = await result
        return result

    async def apply_post_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply governance after routing.
        """
        result = self.governance.post_process(payload, ctx or self._governance_context())
        if inspect.isawaitable(result):
            result = await result
        return result

    def _governance_context(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "component": self.__class__.__name__,
            "component_type": "router",
        }