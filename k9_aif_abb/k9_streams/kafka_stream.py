# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""KafkaEventFabric — Kafka / Confluent / Redpanda / IBM Event Streams SBB."""

import json
import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

from k9_aif_abb.k9_core.streams.base_event_fabric import BaseEventFabric
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope

log = logging.getLogger("KafkaEventFabric")


class KafkaEventFabric(BaseEventFabric):
    """
    Kafka-backed event fabric SBB.

    Compatible with Apache Kafka, Confluent Platform, Confluent Cloud,
    Redpanda, and IBM Event Streams — all Kafka-protocol compatible.

    Credentials are never in config.yaml — use environment variables:
      KAFKA_BOOTSTRAP_SERVERS   broker addresses (else KAFKA_BROKER, else localhost:9092)
      KAFKA_SECURITY_PROTOCOL   PLAINTEXT (default) | SSL | SASL_PLAINTEXT | SASL_SSL,
                                when config does not set security_protocol
      KAFKA_SASL_MECHANISM      PLAIN (default) | SCRAM-SHA-256 | SCRAM-SHA-512
      KAFKA_SASL_USERNAME       for SASL_* (Confluent Cloud: the API key)
      KAFKA_SASL_PASSWORD       for SASL_* (Confluent Cloud: the API secret)

    Confluent Cloud is SASL_SSL + PLAIN. SSL uses the system's trusted CAs.

    Messages need not be K9-AIF envelopes: each topic's envelope mapper
    (``streams.mappers``; default ``auto``: native envelopes and Debezium change
    records) turns the raw message into an ``EventEnvelope``; ``log_line`` handles
    application logs. Unmapped messages are skipped and counted (``unmapped``).

    Consumed events carry ``metadata["transport"] = {"topic", "partition", "offset", "key"}``
    so live state can name the exact record behind each value. A published
    envelope's ``metadata["key"]`` becomes the Kafka message key (keep one entity's
    events in order on one partition).

    Requires: pip install k9-aif[kafka]

    YAML config::

        streams:
          enabled: true
          provider: kafka
          kafka:
            bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
            security_protocol: PLAINTEXT    # PLAINTEXT | SSL | SASL_PLAINTEXT | SASL_SSL
            sasl_mechanism:    PLAIN        # PLAIN | SCRAM-SHA-256 | SCRAM-SHA-512
            auto_offset_reset: latest       # earliest replays the topics (rebuilds live state)
            group_id:          null         # null: every instance reads every event
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._producer = None
        self._consumers: Dict[str, Any] = {}
        self._consumer_threads: Dict[str, threading.Thread] = {}
        self._kafka_cfg = self.config.get("streams", {}).get("kafka", {})
        self.unmapped: Dict[str, int] = {}

    def _mapper_for(self, topic: str):
        from k9_aif_abb.k9_factories.streams_factory import StreamsFactory
        return StreamsFactory.create_mapper(self.config, topic)

    def _to_envelope(self, mapper: Any, msg: Any) -> Optional[EventEnvelope]:
        """One consumed Kafka message → an EventEnvelope via the topic's mapper (None: skip)."""
        from k9_aif_abb.k9_streams.envelope_mappers import decode_value
        key = msg.key.decode("utf-8", errors="replace") if isinstance(msg.key, (bytes, bytearray)) else msg.key
        transport = {"topic": msg.topic, "partition": msg.partition, "offset": msg.offset, "key": key}
        envelope = mapper.map(decode_value(msg.value), transport)
        if envelope is None:
            self.unmapped[msg.topic] = self.unmapped.get(msg.topic, 0) + 1
            log.debug("[KafkaFabric] unmapped message on %s #%s", msg.topic, msg.offset)
            return None
        envelope.metadata = {**(envelope.metadata or {}), "transport": transport}
        return envelope

    def _bootstrap_servers(self) -> str:
        return self._kafka_cfg.get("bootstrap_servers") or os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", os.environ.get("KAFKA_BROKER", "localhost:9092"))

    def _security_kwargs(self) -> Dict[str, Any]:
        protocol = (self._kafka_cfg.get("security_protocol")
                    or os.environ.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")).upper()
        kwargs: Dict[str, Any] = {"security_protocol": protocol}
        if protocol.startswith("SASL"):
            kwargs.update(
                sasl_mechanism=self._kafka_cfg.get("sasl_mechanism")
                or os.environ.get("KAFKA_SASL_MECHANISM", "PLAIN"),
                sasl_plain_username=os.environ.get("KAFKA_SASL_USERNAME", ""),
                sasl_plain_password=os.environ.get("KAFKA_SASL_PASSWORD", ""),
            )
        return kwargs

    def _ensure_producer(self) -> None:
        if self._producer is not None:
            return
        try:
            from kafka import KafkaProducer  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pip install k9-aif[kafka] required for KafkaEventFabric") from exc

        self._producer = KafkaProducer(
            bootstrap_servers=self._bootstrap_servers(),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
            **self._security_kwargs(),
        )
        log.info("[KafkaFabric] Producer connected to %s", self._bootstrap_servers())

    def publish(self, envelope: EventEnvelope, topic: str) -> None:
        self._ensure_producer()
        key = envelope.metadata.get("key") if isinstance(envelope.metadata, dict) else None
        self._producer.send(topic, value=envelope.to_dict(), key=key)
        log.debug("[KafkaFabric] Published %s → %s", envelope.event_type, topic)

    def subscribe(self, topic: str, callback: Callable[[EventEnvelope], None]) -> None:
        try:
            from kafka import KafkaConsumer  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pip install k9-aif[kafka] required for KafkaEventFabric") from exc

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap_servers(),
            auto_offset_reset=self._kafka_cfg.get("auto_offset_reset", "latest"),
            group_id=self._kafka_cfg.get("group_id"),
            enable_auto_commit=self._kafka_cfg.get("group_id") is not None,
            **self._security_kwargs(),
        )
        self._consumers[topic] = consumer
        mapper = self._mapper_for(topic)

        def _consume() -> None:
            log.info("[KafkaFabric] Consumer started on topic: %s", topic)
            for msg in consumer:
                try:
                    envelope = self._to_envelope(mapper, msg)
                    if envelope is not None:
                        callback(envelope)
                except Exception as exc:
                    log.error("[KafkaFabric] Error on %s: %s", topic, exc)

        thread = threading.Thread(target=_consume, daemon=True, name=f"k9-stream-{topic}")
        self._consumer_threads[topic] = thread
        thread.start()

    def flush(self, timeout: Optional[float] = None) -> None:
        """Wait until published events have reached the broker."""
        if self._producer:
            self._producer.flush(timeout=timeout)

    def unsubscribe(self, topic: str) -> None:
        consumer = self._consumers.pop(topic, None)
        if consumer:
            consumer.close()
        self._consumer_threads.pop(topic, None)

    def close(self) -> None:
        if self._producer:
            self._producer.close()
            self._producer = None
        for consumer in self._consumers.values():
            consumer.close()
        self._consumers.clear()
        self._consumer_threads.clear()
