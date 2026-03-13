# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Base Agent
# Core abstract base for all K9-AIF domain and orchestration agents.

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseAgent(ABC):
    """
    BaseAgent
    =========
    Abstract foundation for all K9-AIF agents (domain, orchestration, or utility).

    Each agent:
      - Executes a single, well-defined function (`execute()`).
      - Publishes structured events through an optional message bus.
      - Records operational activity through an optional monitor.
      - Operates under the K9-AIF governance and observability model.

    This class **must not** import any higher-layer modules (such as Orchestrator or Router)
    to prevent circular dependencies. All integrations occur via interfaces (monitor, message_bus).

    Attributes
    ----------
    layer : str
        Logical layer identifier used for logging and monitoring.
    config : Dict[str, Any]
        Configuration dictionary passed during initialization.
    monitor : Optional[Any]
        Optional monitoring object implementing `record_event(event: Dict)`.
    message_bus : Optional[Any]
        Optional messaging interface implementing `publish(event: Dict)`.
    logger : logging.Logger
        Logger scoped to the agent class.
    """

    layer: str = "Agent Base"

    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, message_bus=None):
        """
        Initialize the base agent.

        Parameters
        ----------
        config : Dict[str, Any], optional
            Configuration values for the agent instance.
        monitor : object, optional
            Monitoring instance for observability hooks.
        message_bus : object, optional
            Message bus instance for publishing structured events.
        """
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    # ------------------------------------------------------------------
    @abstractmethod
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent's primary logic.

        Subclasses **must** implement this method to perform their
        core business or orchestration function.

        Parameters
        ----------
        payload : Dict[str, Any]
            Input data structure (task request, document, or event).

        Returns
        -------
        Dict[str, Any]
            Standardized response or result payload.
        """
        raise NotImplementedError("Subclasses must implement execute()")

    # ------------------------------------------------------------------
    def publish_event(self, event: Dict[str, Any]):
        """
        Publish a structured event to the message bus and/or monitor.

        Parameters
        ----------
        event : Dict[str, Any]
            Structured event dictionary containing context and data.

        Notes
        -----
        - The method is optional for agents that emit lifecycle or
          telemetry events.
        - Both `message_bus` and `monitor` parameters are optional; if
          not set, this call is silently ignored.
        """
        if self.message_bus:
            self.message_bus.publish(event)
        if self.monitor:
            self.monitor.record_event(event)
        self.logger.info(f"[{self.layer}] Event published: {event}")