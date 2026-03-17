# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/orchestration/data_transformation_orchestrator.py

import time
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_factories.message_factory import MessageFactory


class DataTransformationOrchestrator(BaseOrchestrator):
    """
    K9-AIF Orchestrator SBB - DataTransformationOrchestrator
    --------------------------------------------------------
    Coordinates data-transformation workflows between ABB layers.
    Emits structured telemetry to the K9EventBus (Redpanda/Kafka) for monitoring and auditing.
    """

    def __init__(self, config: Dict[str, Any], monitor=None):
        super().__init__(monitor=monitor, config=config)
        self.config = config
        self.bus = MessageFactory.create(config)
        self.topic = config.get("messaging", {}).get("topic", "k9aif-events")

    # ------------------------------------------------------------------
    # Core orchestration lifecycle
    # ------------------------------------------------------------------
    def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish structured telemetry to the message bus."""
        event = {
            "orchestrator": self.__class__.__name__,
            "event_type": event_type,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topic": self.topic,
            "payload": payload,
        }
        try:
            self.bus.publish(event)
        except Exception as e:
            self.logger.warning(f"Failed to emit event: {e}")

    # ------------------------------------------------------------------
    # Required abstract implementation (BaseOrchestrator contract)
    # ------------------------------------------------------------------
    def executeFlow(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Concrete orchestration entry point.
        Performs transformation and emits telemetry events at each stage.
        """
        task_id = task.get("id", "unknown")
        self.emit_event("start", {"task_id": task_id, "status": "initiated"})
        self.logger.info(f"[DataTransformation] Starting transformation for {task_id}")

        try:
            # Simulated transformation
            time.sleep(0.5)
            transformed = {k.upper(): str(v).strip() for k, v in task.items()}
            self.emit_event("success", {"task_id": task_id, "result": transformed})
            self.logger.info(f"[DataTransformation] Completed for {task_id}")
            return {"status": "success", "data": transformed}

        except Exception as e:
            self.emit_event("error", {"task_id": task_id, "error": str(e)})
            self.logger.error(f"[DataTransformation] Failed for {task_id}: {e}")
            return {"status": "failed", "error": str(e)}

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Async wrapper for executeFlow() for backward compatibility."""
        return self.executeFlow(task)
    
    # ------------------------------------------------------------------
    # Optional cleanup
    # ------------------------------------------------------------------
    def close(self):
        """Gracefully close message-bus connection."""
        try:
            if self.bus:
                self.bus.close()
                self.logger.info("Closed DataTransformationOrchestrator bus connection.")
        except Exception as e:
            self.logger.debug(f"Bus close failed: {e}")