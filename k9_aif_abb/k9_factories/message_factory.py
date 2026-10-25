# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/message_factory.py

from __future__ import annotations
from typing import Any, Dict
import logging, threading, json

from k9_aif_abb.k9_core.messaging.k9_event_bus import DEFAULT_GROUP_ID, K9EventBus
from k9_aif_abb.k9_core.messaging.base_queue import LocalQueue
from k9_aif_abb.k9_core.messaging.messaging_errors import MessagingUnavailableError

DEFAULT_TOPIC = "k9aif-events"


class _LocalBusAdapter:
    """In-process bus: events stay inside this process. Used for backend ``local`` (the default) and,
    outside production, when Kafka/Redpanda cannot be reached."""

    def __init__(self, q: LocalQueue, topic: str):
        self._q = q
        self.topic = topic

    def publish(self, event: dict):
        payload_bytes = len(json.dumps(event).encode("utf-8"))
        logging.getLogger("MessageFactory").debug("[LocalBusAdapter] queued local event (%.2f KB)", payload_bytes / 1024)
        self._q.send(event.get("task_id", ""), event)

    def subscribe(self, callback, *, from_beginning: bool = False, group_id=None):
        import time

        def _loop():
            while True:
                msg = self._q.receive()
                if msg:
                    callback(msg["payload"])
                else:
                    time.sleep(0.05)

        threading.Thread(target=_loop, daemon=True).start()

    def close(self):
        return


class MessageFactory:
    """
    Messaging ABB Factory (Singleton)
    ---------------------------------
    Creates or reuses a configured event bus instance from config.yaml.

    Example config:
      messaging:
        backend: redpanda
        brokers:
          - localhost:9092
        topic: acme-events
        group_id: acme-console
        security_protocol: PLAINTEXT   # PLAINTEXT (default) | SASL_SSL
        sasl_mechanism:    PLAIN       # PLAIN | SCRAM-SHA-256 | SCRAM-SHA-512
        # Credentials: KAFKA_SASL_USERNAME / KAFKA_SASL_PASSWORD from env only
        allow_local_fallback: false    # true: if the broker is unreachable, use an in-process
                                       # queue even in production (events stay in this process)

    With backend kafka/redpanda, a broker that cannot be reached at start-up raises
    :class:`MessagingUnavailableError` in production instead of quietly switching to an
    in-process queue that no other process can read. Outside production it falls back with a
    warning. Keeping the shared default ``topic``/``group_id`` logs a warning: two applications
    on them split each other's messages.
    """

    _singleton = None
    _lock = threading.Lock()

    # ------------------------------------------------------------------
    # Create or reuse
    # ------------------------------------------------------------------
    @classmethod
    def create(cls, config: Dict[str, Any], monitor: Any = None):
        """Create or reuse the singleton MessageBus."""
        if cls._singleton:
            return cls._singleton

        logger = logging.getLogger("MessageFactory")
        mcfg = config.get("messaging", {}) if isinstance(config, dict) else {}
        backend = str(mcfg.get("backend", "local")).lower()
        topic = mcfg.get("topic", DEFAULT_TOPIC)
        group_id = mcfg.get("group_id", DEFAULT_GROUP_ID)

        if backend not in ("redpanda", "kafka"):
            with cls._lock:
                cls._singleton = _LocalBusAdapter(LocalQueue(name="LocalQueue", monitor=monitor), topic)
            logger.info("[MessageFactory] Using the in-process LocalQueue (messaging.backend=%s)", backend)
            return cls._singleton

        if topic == DEFAULT_TOPIC or group_id == DEFAULT_GROUP_ID:
            logger.warning(
                "[MessageFactory] messaging.topic=%s, group_id=%s: the shared defaults. Two applications on "
                "the same Kafka with these names split each other's messages; set your own.", topic, group_id)

        brokers = mcfg.get("brokers", [])
        broker_url = brokers[0] if brokers else mcfg.get("broker_url", "localhost:9092")
        allow_fallback = bool(mcfg.get("allow_local_fallback", False))
        try:
            bus = K9EventBus(
                backend=backend,
                broker_url=broker_url,
                topic=topic,
                group_id=group_id,
                auto_create=bool(mcfg.get("auto_create", True)),
                security_protocol=mcfg.get("security_protocol", "PLAINTEXT"),
                sasl_mechanism=mcfg.get("sasl_mechanism", "PLAIN"),
                monitor=monitor,
                require_connection=True,
                config=config,
            )
        except Exception as e:
            from k9_aif_abb.k9_core.governance.pipeline import is_permissive_env
            if not (allow_fallback or is_permissive_env()):
                if isinstance(e, MessagingUnavailableError):
                    raise
                raise MessagingUnavailableError(f"Message bus initialization failed: {e}") from e
            logger.warning("[MessageFactory] %s unavailable (%s): using an in-process LocalQueue; events will "
                           "not reach other processes.", backend, e)
            with cls._lock:
                cls._singleton = _LocalBusAdapter(LocalQueue(name="FallbackLocalQueue", monitor=monitor), topic)
            return cls._singleton

        with cls._lock:
            cls._singleton = bus
        logger.info(f"[MessageFactory] [OK] Connected to {backend.capitalize()} at {broker_url}")
        return cls._singleton

    # ------------------------------------------------------------------
    # Unified publish (for all backends)
    # ------------------------------------------------------------------
    @classmethod
    def publish(cls, event: Dict[str, Any]):
        """Publish a JSON event on the active bus (Kafka/Redpanda or LocalQueue). Errors raise (1.20).

        ``event["topic"]`` picks the topic on Kafka/Redpanda. Before 1.20 this looked for a confluent-style
        ``producer`` the bus doesn't have, and printed and dropped any error.
        """
        if not cls._singleton:
            raise RuntimeError("MessageFactory not initialized; call create(config) first.")
        topic = event.get("topic")
        if topic and hasattr(cls._singleton, "publish_to"):
            cls._singleton.publish_to(topic, event)
        else:
            cls._singleton.publish(event)

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------
    @classmethod
    def get_global(cls):
        if cls._singleton:
            return cls._singleton
        raise RuntimeError("MessageFactory has no active MessageBus. Call create() first.")

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._singleton is not None

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._singleton = None
        logging.getLogger("MessageFactory").info("MessageFactory reset complete.")