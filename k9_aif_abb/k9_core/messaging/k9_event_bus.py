# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/messaging/k9_event_bus.py

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from kafka import KafkaProducer, KafkaConsumer

from k9_aif_abb.k9_core.messaging.messaging_errors import LargeEventError, MessagingUnavailableError

# The group every consumer gets when it names none. Two applications consuming one topic in the same
# group split its messages between them (each event reaches only one), so a consumer using it is warned.
DEFAULT_GROUP_ID = "k9aif-core"

# Large events (1.20): an event over max_event_bytes is stored in object storage and the event on Kafka
# carries its link under this key; consumers on this bus fetch it back before the callback sees it.
LARGE_EVENT_KEY = "k9_large_event"
DEFAULT_LARGE_EVENTS_BUCKET = "k9aif-large-events"
DEFAULT_LARGE_EVENTS_TTL_DAYS = 30
LARGE_EVENTS_PREFIX = "large-events/"
# Small routing fields copied onto the link event, so a router or filter can still read them.
_LINK_EVENT_FIELDS = ("event_type", "correlation_id", "job_id", "task_id", "meta", "topic")


class K9EventBus:
    """
    Core ABB: K9EventBus
    --------------------
    Unified event bus abstraction for Redpanda / Kafka.

    **Large events (1.20).** An event bigger than ``max_event_bytes`` (512 KB) is stored in object storage
    and the event published to Kafka carries its link instead (``k9_large_event``: uri, bucket, key, size,
    sha256), plus the small routing fields (``event_type``, ``correlation_id``, ...). ``subscribe()`` and
    ``subscribe_async()`` fetch it back, check its hash and hand the callback the original event, so
    neither side changes. Before 1.20 the event was replaced by ``{"truncated": true}`` and sent anyway.

    Config (``messaging.large_events``, all optional)::

        messaging:
          large_events:
            bucket: k9aif-large-events   # the framework default
            ttl_days: 30                  # objects under large-events/ expire; 0 = leave lifecycle to you

    The store is the application's ``object_storage`` (S3, MinIO, IBM COS, local or your own). With no
    ``object_storage`` block, development and test use local files and production raises
    :class:`LargeEventError`: local files can't be read by another host. A failed upload raises too;
    the event is never sent without its content. Send errors raise to the caller.

    Security is PLAINTEXT by default (backward compatible — existing
    deployments are unaffected). To enable SASL_SSL, opt in explicitly:

        security_protocol: SASL_SSL
        sasl_mechanism:    PLAIN   # or SCRAM-SHA-256 / SCRAM-SHA-512

    Credentials are never read from config.yaml — set them via environment
    variables only:
      KAFKA_SASL_USERNAME
      KAFKA_SASL_PASSWORD

    In production (``K9_ENV`` not development/dev/test) a broker that cannot be reached at start-up
    raises :class:`MessagingUnavailableError`: a bus without a producer would drop every event while
    the application looked healthy. ``require_connection=False`` keeps the old degrade-and-warn
    behaviour for a caller that truly wants it; development and test degrade by default.
    """

    def __init__(
        self,
        backend: str = "kafka",
        broker_url: str = "localhost:9092",
        topic: str = "k9aif-events",
        group_id: str = DEFAULT_GROUP_ID,
        auto_create: bool = True,
        max_event_bytes: int = 512 * 1024,
        security_protocol: str = "PLAINTEXT",
        sasl_mechanism: str = "PLAIN",
        monitor: Optional[Any] = None,
        require_connection: Optional[bool] = None,
        config: Optional[Dict[str, Any]] = None,
        object_store: Optional[Any] = None,
        **kwargs,
    ):
        self.backend = backend
        self.broker_url = broker_url
        self.topic = topic
        self.group_id = group_id
        self.auto_create = auto_create
        self.max_event_bytes = max_event_bytes
        self.security_protocol = security_protocol
        self.sasl_mechanism = sasl_mechanism
        self.monitor = monitor
        self.log = logging.getLogger("K9EventBus")
        self._producer: Optional[KafkaProducer] = None
        self._config = config or {}
        large = ((self._config.get("messaging") or {}).get("large_events") or {})
        self.large_events_bucket = large.get("bucket") or DEFAULT_LARGE_EVENTS_BUCKET
        ttl = large.get("ttl_days", DEFAULT_LARGE_EVENTS_TTL_DAYS)
        self.large_events_ttl_days = int(ttl) if ttl else 0
        self._object_store = object_store
        self._store_lock = threading.Lock()
        self._bucket_ready = False

        try:
            # --- Safe integer conversion for all numeric params ---
            retries = int(os.environ.get("K9_PRODUCER_RETRIES", 3))
            linger_ms = int(os.environ.get("K9_PRODUCER_LINGER_MS", 0))
            max_request_size = int(os.environ.get("K9_PRODUCER_MAX_REQUEST_SIZE", 2 * 1024 * 1024))
            request_timeout_ms = int(os.environ.get("K9_PRODUCER_TIMEOUT_MS", 30000))
            # Stay under Redpanda's idle connection timeout (~5 min default)
            connections_max_idle_ms = int(os.environ.get("K9_PRODUCER_IDLE_MS", 270000))

            self._producer = KafkaProducer(
                bootstrap_servers=[self.broker_url],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,
                retries=retries,
                linger_ms=linger_ms,
                max_request_size=max_request_size,
                request_timeout_ms=request_timeout_ms,
                connections_max_idle_ms=connections_max_idle_ms,
                **self._security_kwargs(),
            )

            self.log.info(
                f"[K9EventBus] Connected -> {self.broker_url} | topic={self.topic} | group={self.group_id} "
                f"| security_protocol={self.security_protocol}"
            )

        except Exception as e:
            if require_connection is None:
                from k9_aif_abb.k9_core.governance.pipeline import is_permissive_env
                require_connection = not is_permissive_env()
            if require_connection:
                raise MessagingUnavailableError(
                    f"Kafka/Redpanda at {self.broker_url} cannot be reached ({e}). In production K9-AIF "
                    f"refuses to run without its message bus, because every published event would be "
                    f"dropped. Start the broker or fix the broker address; for local work set "
                    f"K9_ENV=development."
                ) from e
            self.log.error(f"[K9EventBus] failed to initialize: {e}; events will NOT be published "
                           f"(allowed outside production)", exc_info=False)
            self._producer = None

    # ----------------------------------------------------------------------
    # Security kwargs — shared by producer, sync consumer, and async consumer
    # ----------------------------------------------------------------------
    def _security_kwargs(self) -> Dict[str, Any]:
        """
        PLAINTEXT (default) adds nothing beyond security_protocol — identical
        connection behavior to before this option existed. SASL_SSL pulls
        credentials from environment variables only, never from config.yaml.
        """
        if self.security_protocol == "PLAINTEXT":
            return {"security_protocol": "PLAINTEXT"}
        return {
            "security_protocol": self.security_protocol,
            "sasl_mechanism": self.sasl_mechanism,
            "sasl_plain_username": os.environ.get("KAFKA_SASL_USERNAME", ""),
            "sasl_plain_password": os.environ.get("KAFKA_SASL_PASSWORD", ""),
        }

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
        """Publish an event to this bus's topic. An event over ``max_event_bytes`` travels as a link."""
        self._send(self.topic, event)

    def _send(self, topic: str, event: Dict[str, Any]) -> None:
        if not self._producer:
            # Only possible in development/test or with require_connection=False (documented degrade)
            self.log.warning("[K9EventBus] no active producer; skipped publish to %s", topic)
            return
        size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        if size > self.max_event_bytes:
            event = self._store_large_event(topic, event, size)
            size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        future = self._producer.send(topic, value=event)
        if hasattr(future, "add_errback"):
            # The broker can still refuse it after send() returns; that must not pass unseen
            future.add_errback(lambda exc: self.log.error(
                "[K9EventBus] broker did not accept event for %s (event_type=%s): %s",
                topic, event.get("event_type"), exc))
        self._log_event_summary(event, size)

    # ----------------------------------------------------------------------
    # Large events: stored in object storage, linked from the event
    # ----------------------------------------------------------------------
    def _store(self):
        with self._store_lock:
            if self._object_store is None:
                from k9_aif_abb.k9_core.governance.pipeline import is_permissive_env
                if not self._config.get("object_storage") and not is_permissive_env():
                    raise LargeEventError(
                        f"An event is larger than {self.max_event_bytes // 1024} KB and no object_storage is "
                        f"configured. Large events are stored in object storage and sent as a link; add an "
                        f"object_storage block (provider: s3 | ibm | your own) to config.yaml. Local files "
                        f"are used only in development and test, because another host can't read them.")
                from k9_aif_abb.k9_factories.object_storage_factory import ObjectStorageFactory
                self._object_store = ObjectStorageFactory.create(self._config)
            if not self._bucket_ready:
                self._object_store.ensure_bucket(self.large_events_bucket)
                if self.large_events_ttl_days:
                    try:
                        applied = self._object_store.set_expiry(
                            self.large_events_bucket, LARGE_EVENTS_PREFIX, self.large_events_ttl_days)
                    except Exception as e:
                        applied = False
                        self.log.error("[K9EventBus] could not set expiry on %s: %s", self.large_events_bucket, e)
                    if not applied:
                        self.log.error(
                            "[K9EventBus] large events in bucket %s will NOT expire: set a %d-day lifecycle "
                            "rule on prefix %s yourself, or messaging.large_events.ttl_days: 0 to silence this.",
                            self.large_events_bucket, self.large_events_ttl_days, LARGE_EVENTS_PREFIX)
                self._bucket_ready = True
            return self._object_store

    def _store_large_event(self, topic: str, event: Dict[str, Any], size: int) -> Dict[str, Any]:
        data = json.dumps(event, ensure_ascii=False).encode("utf-8")
        key = f"{LARGE_EVENTS_PREFIX}{topic}/{time.strftime('%Y-%m-%d')}/{uuid.uuid4().hex}.json"
        try:
            uri = self._store().upload(self.large_events_bucket, key, data,
                                       {"topic": topic, "event_type": str(event.get("event_type", ""))})
        except LargeEventError:
            raise
        except Exception as e:
            raise LargeEventError(
                f"Event for {topic} ({size // 1024} KB) could not be stored in bucket "
                f"{self.large_events_bucket}: {e}. It was not sent.") from e
        link = {k: event[k] for k in _LINK_EVENT_FIELDS if k in event}
        link[LARGE_EVENT_KEY] = {"uri": uri, "bucket": self.large_events_bucket, "key": key,
                                 "size": size, "sha256": hashlib.sha256(data).hexdigest()}
        self.log.info("[K9EventBus] large event (%d KB) for %s stored at %s; sent as a link",
                      size // 1024, topic, uri)
        return link

    def resolve_event(self, value: Any) -> Any:
        """Return the original event for a link event (a no-op for any other value).

        Raises :class:`LargeEventError` when the stored event can't be fetched (expired after
        ``ttl_days``, deleted, store unreachable) or its content doesn't match the hash it was sent with.
        """
        if not isinstance(value, dict) or LARGE_EVENT_KEY not in value:
            return value
        ref = value[LARGE_EVENT_KEY]
        try:
            data = self._store().download(ref["bucket"], ref["key"])
        except LargeEventError:
            raise
        except Exception as e:
            raise LargeEventError(f"Large event {ref.get('uri')} could not be fetched: {e}") from e
        if hashlib.sha256(data).hexdigest() != ref.get("sha256"):
            raise LargeEventError(f"Large event {ref.get('uri')} does not match the hash it was sent with")
        return json.loads(data.decode("utf-8"))

    # ----------------------------------------------------------------------
    # Consume loop (used by ConsoleBridgeAgent)
    # ----------------------------------------------------------------------
    def _warn_if_shared_group(self) -> None:
        if self.group_id == DEFAULT_GROUP_ID:
            self.log.warning(
                "[K9EventBus] consuming %s in the default group '%s': another application doing the same "
                "would split these messages with this one. Give each application (and each process role) "
                "its own group_id.", self.topic, DEFAULT_GROUP_ID)

    def subscribe(self, callback):
        """Listen to the configured topic and stream events to callback."""
        self._warn_if_shared_group()
        try:
            consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=[self.broker_url],
                group_id=self.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                **self._security_kwargs(),
            )
            self.log.info(f"[K9EventBus] Listening -> topic={self.topic}")
            for msg in consumer:
                try:
                    callback(self.resolve_event(msg.value))
                except LargeEventError as e:
                    self.log.error(f"[K9EventBus] event skipped: {e}")
                except Exception as e:
                    self.log.error(f"[K9EventBus] consumer callback failed: {e}")
        except Exception as e:
            self.log.error(f"[K9EventBus] subscribe failed: {e}", exc_info=False)

    # ----------------------------------------------------------------------
    # Async consumer (aiokafka) — awaits group join before yielding messages
    # ----------------------------------------------------------------------
    async def subscribe_async(
        self,
        callback,
        topics: Optional[List[str]] = None,
        pattern: Optional[str] = None,
        session_timeout_ms: int = 30000,
        heartbeat_interval_ms: int = 10000,
        max_poll_interval_ms: int = 600000,
        metadata_max_age_ms: int = 3000,
    ) -> None:
        """
        Async consumer loop using aiokafka.

        ``await consumer.start()`` blocks until the broker group join and
        partition assignment are complete — no probe-poll hack needed.

        Args:
            callback:             async or sync callable receiving the decoded payload dict.
            topics:               list of topic names to subscribe to; defaults to [self.topic].
            pattern:               regex string for pattern subscription (e.g. r"hil\\..*") —
                                   used instead of ``topics`` when the exact topic set is
                                   dynamic (one HIL Router listening across every
                                   ``hil.replies.<orchestrator>`` topic, not one process
                                   per orchestrator type). Mutually exclusive with ``topics``.
            session_timeout_ms:   broker-side session timeout.
            heartbeat_interval_ms: heartbeat frequency (must be < session_timeout_ms / 3).
            max_poll_interval_ms: max time between fetches (set high for slow LLM calls).
            metadata_max_age_ms:  how often the consumer refreshes cluster metadata --
                                   aiokafka's own default is 5 minutes, which delays
                                   discovering a topic created *after* this consumer
                                   started (e.g. the first hil.replies.<queue> for a
                                   queue nobody's escalated to yet) by up to that long.
                                   Kept short and configurable rather than hardcoded.
        """
        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError:
            self.log.error(
                "[K9EventBus] aiokafka not installed — run: pip install aiokafka"
            )
            return

        # G-19: aiokafka's AIOKafkaConsumer constructor has no `pattern`
        # parameter on any version -- pattern subscription is
        # `consumer.subscribe(pattern=...)`, called *after* construction,
        # not a constructor kwarg. Confirmed live: the prior version of
        # this method (`AIOKafkaConsumer(pattern=..., ...)`) raised
        # TypeError against a real broker, so K9EventRouter.
        # listen_for_hil_replies() never actually consumed a single
        # reply -- caught only by a live-integration test, since this
        # framework's own test_hil_roundtrip.py fakes the message bus
        # and never exercises this method's real aiokafka call at all.
        self._warn_if_shared_group()
        consumer = AIOKafkaConsumer(
            bootstrap_servers=[self.broker_url],
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            session_timeout_ms=session_timeout_ms,
            heartbeat_interval_ms=heartbeat_interval_ms,
            max_poll_interval_ms=max_poll_interval_ms,
            metadata_max_age_ms=metadata_max_age_ms,
            **self._security_kwargs(),
        )

        if pattern is not None:
            consumer.subscribe(pattern=pattern)
            subscribe_desc = f"pattern={pattern!r}"
        else:
            subscribe_topics = topics if topics is not None else [self.topic]
            consumer.subscribe(topics=subscribe_topics)
            subscribe_desc = f"topics={subscribe_topics}"

        await consumer.start()
        self.log.info(
            "[K9EventBus] Async consumer READY | %s | group=%s",
            subscribe_desc, self.group_id,
        )

        try:
            async for msg in consumer:
                try:
                    value = await asyncio.to_thread(self.resolve_event, msg.value)
                    if asyncio.iscoroutinefunction(callback):
                        await callback(value)
                    else:
                        callback(value)
                except LargeEventError as e:
                    self.log.error("[K9EventBus] event skipped: %s", e)
                except Exception as e:
                    self.log.error("[K9EventBus] async callback failed: %s", e, exc_info=True)
        finally:
            await consumer.stop()
            self.log.info(
                "[K9EventBus] Async consumer stopped | %s", subscribe_desc
            )

    # ----------------------------------------------------------------------
    # Publish to a specific topic (multi-topic routing)
    # ----------------------------------------------------------------------
    def publish_to(self, topic: str, event: Dict[str, Any]):
        """Publish event to an explicit topic — used by Router, Orchestrators and IntentOrchestrator."""
        self._send(topic, event)

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