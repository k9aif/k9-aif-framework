# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/messaging/k9_event_bus.py

import json
import logging
import os
from typing import Any, Dict, Optional
from kafka import KafkaProducer, KafkaConsumer


class K9EventBus:
    """
    Core ABB: K9EventBus
    --------------------
    Unified event bus abstraction for Redpanda / Kafka.
    Handles small governance/logging events and guards against oversize payloads.
    """

    def __init__(
        self,
        backend: str = "kafka",
        broker_url: str = "localhost:9092",
        topic: str = "k9aif-events",
        group_id: str = "k9aif-core",
        auto_create: bool = True,
        max_event_bytes: int = 512 * 1024,
        monitor: Optional[Any] = None,
        **kwargs,
    ):
        self.backend = backend
        self.broker_url = broker_url
        self.topic = topic
        self.group_id = group_id
        self.auto_create = auto_create
        self.max_event_bytes = max_event_bytes
        self.monitor = monitor
        self.log = logging.getLogger("K9EventBus")
        self._producer: Optional[KafkaProducer] = None

        try:
            # --- Safe integer conversion for all numeric params ---
            retries = int(os.environ.get("K9_PRODUCER_RETRIES", 3))
            linger_ms = int(os.environ.get("K9_PRODUCER_LINGER_MS", 5))
            max_request_size = int(os.environ.get("K9_PRODUCER_MAX_REQUEST_SIZE", 2 * 1024 * 1024))
            request_timeout_ms = int(os.environ.get("K9_PRODUCER_TIMEOUT_MS", 30000))

            self._producer = KafkaProducer(
                bootstrap_servers=[self.broker_url],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,
                retries=retries,
                linger_ms=linger_ms,
                max_request_size=max_request_size,
                request_timeout_ms=request_timeout_ms,
                api_version=(2, 6, 0),
            )

            self.log.info(
                f"[K9EventBus] Connected -> {self.broker_url} | topic={self.topic} | group={self.group_id}"
            )

        except Exception as e:
            self.log.error(f"[K9EventBus] failed to initialize: {e}", exc_info=False)
            self._producer = None

    # ----------------------------------------------------------------------
    # Internal concise logger
    # ----------------------------------------------------------------------
    def _log_event_summary(self, event: Dict[str, Any], size: int):
        """Print a concise 1-line summary with 200-char preview."""
        try:
            preview = json.dumps(event, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "..."
            self.log.debug(f"[K9EventBus] -> {self.topic} | {size/1024:.2f} KB | {preview}")
        except Exception as e:
            self.log.debug(f"[K9EventBus] -> {self.topic} | {size/1024:.2f} KB | [unprintable: {e}]")

    # ----------------------------------------------------------------------
    # Publish event
    # ----------------------------------------------------------------------
    def publish(self, event: Dict[str, Any]):
        """Publish event to Kafka/Redpanda with truncation + concise logging."""
        if not self._producer:
            self.log.warning("[K9EventBus] no active producer; skipped publish")
            return

        try:
            payload = json.dumps(event, ensure_ascii=False)
            size = len(payload.encode("utf-8"))

            # --- Truncate oversize ---
            if size > self.max_event_bytes:
                event = {
                    "meta": event.get("meta", {}),
                    "payload": {"truncated": True, "original_size": size},
                }
                self.log.warning(
                    f"[K9EventBus] truncated large message ({size//1024} KB -> {self.max_event_bytes//1024} KB)"
                )
                payload = json.dumps(event, ensure_ascii=False)
                size = len(payload.encode("utf-8"))

            self._producer.send(self.topic, value=event)
            self._log_event_summary(event, size)

        except Exception as e:
            self.log.error(f"[K9EventBus] publish failed: {e}", exc_info=False)

    # ----------------------------------------------------------------------
    # Consume loop (used by ConsoleBridgeAgent)
    # ----------------------------------------------------------------------
    def subscribe(self, callback):
        """Listen to the configured topic and stream events to callback."""
        try:
            consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=[self.broker_url],
                group_id=self.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            self.log.info(f"[K9EventBus] Listening -> topic={self.topic}")
            for msg in consumer:
                try:
                    callback(msg.value)
                except Exception as e:
                    self.log.error(f"[K9EventBus] consumer callback failed: {e}")
        except Exception as e:
            self.log.error(f"[K9EventBus] subscribe failed: {e}", exc_info=False)

    # ----------------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------------
    def close(self):
        """Gracefully close producer connection."""
        try:
            if self._producer:
                self._producer.flush()
                self._producer.close()
            self.log.info("[K9EventBus] stopped")
        except Exception:
            pass