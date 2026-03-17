# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/orchestration/data_transformation_orchestrator.py

import asyncio
import time
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_factories.message_factory import MessageFactory


class DataTransformationOrchestrator(BaseOrchestrator):
    """
    K9-AIF - Data Transformation Orchestrator
    -----------------------------------------
    Orchestrates data transformation agents and publishes governed telemetry
    events through the unified K9-AIF MessageBus (Redpanda, Kafka, etc.).
    """

    def __init__(self, config: Dict[str, Any], monitor=None, message_bus=None):
        super().__init__(monitor=monitor, config=config)
        self.config = config
        self.bus = message_bus or MessageFactory.create(config)
        self.topic = config.get("messaging", {}).get("topic", "k9aif-test")

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Perform transformation and emit structured events."""
        await self.log(f"Starting transformation for task {task.get('id')}", level="INFO")

        event_start = {
            "orchestrator": "DataTransformationOrchestrator",
            "event_type": "start",
            "task_id": task.get("id"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        self.bus.publish(event_start)

        try:
            # Simulated transformation
            await asyncio.sleep(0.5)
            transformed = {k.upper(): str(v).strip() for k, v in task.items()}

            event_done = {
                "orchestrator": "DataTransformationOrchestrator",
                "event_type": "success",
                "task_id": task.get("id"),
                "result": transformed,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
            }
            self.bus.publish(event_done)

            await self.log(f"Transformation complete for task {task.get('id')}", level="INFO")
            return {"status": "success", "data": transformed}

        except Exception as e:
            event_fail = {
                "orchestrator": "DataTransformationOrchestrator",
                "event_type": "error",
                "task_id": task.get("id"),
                "error": str(e),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
            }
            self.bus.publish(event_fail)
            await self.log(f"Error: {e}", level="ERROR")
            return {"status": "failed", "error": str(e)}

    def close(self):
        if self.bus:
            self.bus.close()