# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - Base Router
# Central abstract router that directs payloads to orchestrators by intent.

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseRouter(ABC):
    """
    BaseRouter
    ==========
    Abstract foundation for routing logic in the K9-AIF framework.

    Purpose
    --------
    The BaseRouter defines how incoming payloads (documents, events,
    or datasets) are normalized, classified by intent, and dispatched
    to the appropriate orchestrator instance.

    Design Rules
    -------------
    - Must never import concrete orchestrators or agents directly to
      prevent circular dependencies.
    - Maintains a dynamic registry mapping intents -> orchestrators.
    - Routes execution requests using configuration-driven logic.

    Attributes
    ----------
    layer : str
        Logical layer identifier for logging and monitoring.
    config : Dict[str, Any]
        Configuration dictionary defining routing behavior.
    monitor : Optional[Any]
        Optional monitoring object implementing `record_event(event: Dict)`.
    message_bus : Optional[Any]
        Optional message bus implementing `publish(event: Dict)`.
    registry : Dict[str, Any]
        Dynamic registry of intent names to orchestrator instances.
    logger : logging.Logger
        Scoped logger for routing operations.
    """

    layer: str = "Router Base"

    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, message_bus=None):
        """
        Initialize the base router.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration dictionary for router behavior.
        monitor : object, optional
            Monitoring instance for observability hooks.
        message_bus : object, optional
            Message bus instance for event publishing.
        """
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        self.registry: Dict[str, Any] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    # ------------------------------------------------------------------
    def register_orchestrator(self, intent: str, orchestrator: Any):
        """
        Register an orchestrator instance for a given intent.

        Parameters
        ----------
        intent : str
            Unique key identifying the intent (e.g., 'claims_intake').
        orchestrator : Any
            The orchestrator instance responsible for handling that intent.

        Notes
        -----
        This method enables flexible runtime registration of orchestrators
        without hard-coded references.
        """
        self.registry[intent] = orchestrator
        self.logger.info(f"[{self.layer}] Registered orchestrator for intent: {intent}")

    # ------------------------------------------------------------------
    @abstractmethod
    def route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route a payload to the appropriate orchestrator based on intent.

        Subclasses must implement intent detection and routing logic.

        Parameters
        ----------
        payload : Dict[str, Any]
            Incoming data or event requiring orchestration.

        Returns
        -------
        Dict[str, Any]
            The orchestrator's processed response payload.
        """
        raise NotImplementedError("Subclasses must implement route()")

    # ------------------------------------------------------------------
    def normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize the input payload before routing.

        Parameters
        ----------
        payload : Dict[str, Any]
            Raw input data or event.

        Returns
        -------
        Dict[str, Any]
            Normalized payload ready for intent recognition and routing.

        Notes
        -----
        Default implementation performs no transformation, but subclasses
        can override this method to enforce structure or schema validation.
        """
        return payload