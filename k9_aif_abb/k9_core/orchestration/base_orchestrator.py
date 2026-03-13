# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Base Orchestrator
# Abstract orchestrator foundation for coordinating multiple agents.

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseOrchestrator(ABC):
    """
    BaseOrchestrator
    =================
    Abstract base class for all orchestrators in the K9-AIF framework.

    Purpose
    --------
    Provides a standardized structure for coordinating agent execution
    flows, maintaining observability, and ensuring consistent event
    publishing through the K9-AIF message bus and monitor.

    Design Guidelines
    -----------------
    - This class must not import or directly reference higher layers
      (e.g., Router or UI components) to prevent circular imports.
    - Subclasses implement `execute_flow()` to define orchestration logic.
    - Each orchestrator operates under governance and monitoring hooks.

    Attributes
    ----------
    layer : str
        Logical layer identifier used for monitoring and logging context.
    config : Dict[str, Any]
        Configuration dictionary passed at initialization.
    monitor : Optional[Any]
        Monitoring object implementing `record_event(event: Dict)`.
    message_bus : Optional[Any]
        Message bus interface implementing `publish(event: Dict)`.
    logger : logging.Logger
        Scoped logger for orchestration activities.
    """

    layer: str = "Orchestrator Base"

    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, message_bus=None):
        """
        Initialize the orchestrator base.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration parameters for orchestration behavior.
        monitor : object, optional
            Monitoring instance to record orchestration events.
        message_bus : object, optional
            Messaging interface to publish flow-level updates.
        """
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    # ------------------------------------------------------------------
    @abstractmethod
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the orchestration flow across registered agents.

        This method must be overridden in each concrete orchestrator to
        define its execution sequence and agent coordination logic.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input data or context to be processed by agents.

        Returns
        -------
        Dict[str, Any]
            Aggregated response or final orchestration output.
        """
        raise NotImplementedError("Subclasses must implement execute_flow()")

    # ------------------------------------------------------------------
    def publish_status(self, status: str, context: Dict[str, Any]):
        """
        Publish a status event for observability and governance tracking.

        Parameters
        ----------
        status : str
            Status message or lifecycle stage identifier (e.g., 'started', 'completed').
        context : Dict[str, Any]
            Contextual metadata to accompany the status event.

        Notes
        -----
        This method is used by orchestrators to record internal progress
        or notify other components of lifecycle changes.
        """
        event = {"status": status, **context}
        if self.message_bus:
            self.message_bus.publish(event)
        if self.monitor:
            self.monitor.record_event(event)
        self.logger.info(f"[{self.layer}] Status event: {event}")