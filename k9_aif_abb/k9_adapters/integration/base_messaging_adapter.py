# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseMessagingAdapter — ABB for event bus connectors (Kafka, RabbitMQ, SQS/SNS,
Azure Service Bus, IBM MQ).

A Messaging Adapter is NOT a leaf node — on the K9X Studio canvas it can chain
to a Workflow Adapter or Process Flow Adapter downstream (event triggers flow).

Concrete SBBs implement publish() and/or consume(); execute() is the template.
Config keys: topic, queue, broker, mode (publish | consume | both).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional

from .base_integration_adapter import BaseIntegrationAdapter


class BaseMessagingAdapter(BaseIntegrationAdapter):
    """ABB for deterministic message bus publish/consume — no LLM inference."""

    @abstractmethod
    def publish(self, topic: str, message: Dict[str, Any]) -> Any:
        """Publish a message to the topic/queue. Return delivery confirmation."""

    def consume(self, topic: str) -> Optional[Dict[str, Any]]:
        """Consume the next message from the topic/queue. Override when needed."""
        raise NotImplementedError(f"{self.adapter_name} does not implement consume()")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        topic = self.config.get("topic") or self.config.get("queue") or payload.get("topic", "")
        mode  = self.config.get("mode", "publish")
        try:
            if mode == "consume":
                result = self.consume(topic)
                return {"adapter": self.adapter_name, "status": "success", "mode": "consume", "message": result}
            result = self.publish(topic, payload)
            return {"adapter": self.adapter_name, "status": "success", "mode": "publish", "result": result}
        except Exception as exc:
            return self.handle_error(exc, payload)
