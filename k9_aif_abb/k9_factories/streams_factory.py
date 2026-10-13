# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
StreamsFactory — static factory for K9 enterprise context fabric providers.

Pre-registered providers: in_memory (default, zero deps), kafka.
Live state (1.17): in_memory; register Redis/PostgreSQL states with register_state().

YAML config::

    streams:
      enabled: false            # false by default — opt-in, zero impact on existing code
      provider: in_memory       # in_memory (default) | kafka
      window:
        max_events:  500        # max events retained in context window
        ttl_seconds: 86400      # event TTL in seconds (24h default)
      kafka:
        bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
        security_protocol: PLAINTEXT
      state:
        provider: in_memory     # in_memory (default) | a registered name
        max_age_seconds: 120    # older values are reported stale
      gate: governance          # governance (default) | noop (development/test only)
      mappers:                  # raw message → EventEnvelope, per topic
        default: auto           # native envelopes + Debezium change records
        app-logs: {type: log_line, source_system: billing-api}

Usage::

    from k9_aif_abb.k9_factories.streams_factory import StreamsFactory

    fabric = StreamsFactory.create_fabric(config)   # None when disabled
    window = StreamsFactory.create_window(config)   # None when disabled
    state  = StreamsFactory.create_state(config, projections=[...])   # None when disabled
    gate   = StreamsFactory.create_gate(config)     # governance from config, or passed in
"""

import logging
from threading import Lock
from typing import Any, Dict, Optional, Type

log = logging.getLogger("StreamsFactory")


class StreamsFactory:
    """Static factory for K9 enterprise context fabric and context window providers."""

    _fabric_registry: Dict[str, Type[Any]] = {}
    _window_registry: Dict[str, Type[Any]] = {}
    _state_registry: Dict[str, Type[Any]] = {}
    _mapper_registry: Dict[str, Type[Any]] = {}
    _lock = Lock()
    _bootstrapped = False

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("StreamsFactory is static and cannot be instantiated")

    @staticmethod
    def _ensure_defaults() -> None:
        if StreamsFactory._bootstrapped:
            return
        with StreamsFactory._lock:
            if StreamsFactory._bootstrapped:
                return
            from k9_aif_abb.k9_streams.in_memory_stream import (
                InMemoryContextWindow,
                InMemoryEventFabric,
            )
            StreamsFactory._fabric_registry["in_memory"] = InMemoryEventFabric
            StreamsFactory._window_registry["in_memory"] = InMemoryContextWindow
            from k9_aif_abb.k9_streams.context_state import InMemoryContextState
            StreamsFactory._state_registry["in_memory"] = InMemoryContextState
            from k9_aif_abb.k9_streams.envelope_mappers import BUILTIN_MAPPERS
            StreamsFactory._mapper_registry.update(BUILTIN_MAPPERS)
            StreamsFactory._bootstrapped = True
            log.info("[Factory] Bootstrapped StreamsFactory")

    @staticmethod
    def register_fabric(name: str, cls: Type[Any]) -> None:
        """Register a custom BaseEventFabric implementation."""
        StreamsFactory._ensure_defaults()
        with StreamsFactory._lock:
            StreamsFactory._fabric_registry[name.lower()] = cls

    @staticmethod
    def register_window(name: str, cls: Type[Any]) -> None:
        """Register a custom BaseContextWindow implementation."""
        StreamsFactory._ensure_defaults()
        with StreamsFactory._lock:
            StreamsFactory._window_registry[name.lower()] = cls

    @staticmethod
    def register_state(name: str, cls: Type[Any]) -> None:
        """Register a custom BaseContextState implementation (Redis, PostgreSQL...)."""
        StreamsFactory._ensure_defaults()
        with StreamsFactory._lock:
            StreamsFactory._state_registry[name.lower()] = cls

    @staticmethod
    def register_mapper(name: str, cls: Type[Any]) -> None:
        """Register a custom BaseEnvelopeMapper (a SaaS webhook format, Avro...)."""
        StreamsFactory._ensure_defaults()
        with StreamsFactory._lock:
            StreamsFactory._mapper_registry[name.lower()] = cls

    @staticmethod
    def create_mapper(config: Optional[Dict[str, Any]] = None, topic: Optional[str] = None):
        """
        The envelope mapper for one topic: ``streams.mappers[topic]``, else
        ``streams.mappers.default``, else ``auto``. An entry is a name or a dict
        with ``type`` plus that mapper's settings.
        """
        StreamsFactory._ensure_defaults()
        mappers = ((config or {}).get("streams") or {}).get("mappers") or {}
        spec = mappers.get(topic) if topic and topic in mappers else mappers.get("default", "auto")
        settings: Dict[str, Any] = {}
        if isinstance(spec, dict):
            settings = {k: v for k, v in spec.items() if k != "type"}
            spec = spec.get("type", "auto")
        cls = StreamsFactory._mapper_registry.get(str(spec).lower())
        if not cls:
            raise ValueError(f"Unknown envelope mapper: {spec}")
        return cls(settings)

    @staticmethod
    def create_fabric(config: Optional[Dict[str, Any]] = None):
        """
        Create a BaseEventFabric from config, or return None if streams are disabled.

        Returns None when config["streams"]["enabled"] is false or absent.
        All stream hooks in Router/Orchestrator are guarded — zero impact on
        existing code when streams are disabled.
        """
        StreamsFactory._ensure_defaults()
        cfg = config or {}
        streams_cfg = cfg.get("streams", {})

        if not streams_cfg.get("enabled", False):
            log.debug("[Factory] Streams disabled — returning None")
            return None

        provider = streams_cfg.get("provider", "in_memory").lower()

        if provider == "kafka" and "kafka" not in StreamsFactory._fabric_registry:
            try:
                from k9_aif_abb.k9_streams.kafka_stream import KafkaEventFabric
                StreamsFactory._fabric_registry["kafka"] = KafkaEventFabric
            except ImportError as exc:
                raise RuntimeError(
                    "pip install k9-aif[kafka] required for streams.provider: kafka"
                ) from exc

        cls = StreamsFactory._fabric_registry.get(provider)
        if not cls:
            raise ValueError(f"Unknown stream fabric provider: {provider}")

        log.info("[Factory] Creating event fabric: provider=%s", provider)
        return cls(config=cfg)

    @staticmethod
    def create_window(config: Optional[Dict[str, Any]] = None):
        """
        Create a BaseContextWindow from config, or return None if streams are disabled.
        """
        StreamsFactory._ensure_defaults()
        cfg = config or {}
        streams_cfg = cfg.get("streams", {})

        if not streams_cfg.get("enabled", False):
            return None

        window_provider = streams_cfg.get("window_provider", "in_memory").lower()
        cls = StreamsFactory._window_registry.get(window_provider) \
            or StreamsFactory._window_registry.get("in_memory")

        log.info("[Factory] Creating context window: provider=%s", window_provider)
        return cls(config=cfg)

    @staticmethod
    def create_state(config: Optional[Dict[str, Any]] = None, projections=None):
        """
        Create a BaseContextState (live per-entity state) from config, with the
        application's projections registered, or None if streams are disabled.
        """
        StreamsFactory._ensure_defaults()
        cfg = config or {}
        streams_cfg = cfg.get("streams", {})
        if not streams_cfg.get("enabled", False):
            return None
        provider = str((streams_cfg.get("state") or {}).get("provider", "in_memory")).lower()
        cls = StreamsFactory._state_registry.get(provider)
        if not cls:
            raise ValueError(f"Unknown context state provider: {provider}")
        log.info("[Factory] Creating context state: provider=%s", provider)
        return cls(config=cfg, projections=projections)

    @staticmethod
    def create_gate(config: Optional[Dict[str, Any]] = None, governance: Any = None):
        """
        The fabric's ingress gate. ``streams.gate: governance`` (default) screens every
        event with ``governance`` — or, when none is passed, the application's own
        (``governance_from_config``: security.shield / governance.guardian).
        With no governance, or ``streams.gate: noop``, events pass unscreened, which
        is allowed only in development/test (K9_ENV); production refuses.
        """
        from k9_aif_abb.k9_core.governance.pipeline import governance_from_config, is_permissive_env
        from k9_aif_abb.k9_core.streams.event_governance_gate import NoopGovernanceGate
        from k9_aif_abb.k9_streams.governance_event_gate import GovernanceEventGate

        cfg = config or {}
        mode = str((cfg.get("streams") or {}).get("gate", "governance")).lower()
        gov = governance if governance is not None else (
            governance_from_config(cfg) if mode == "governance" else None)
        if gov is not None and mode == "governance":
            return GovernanceEventGate(gov)
        if is_permissive_env(cfg.get("k9_env")):
            log.warning("[Factory] Stream events are NOT screened (no governance; K9_ENV allows it)")
            return NoopGovernanceGate()
        raise PermissionError(
            "Stream events must be governed outside development/test: configure "
            "security.shield (or governance.guardian), or pass governance= to create_gate()")
