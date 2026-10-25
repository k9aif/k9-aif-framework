# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Factories keep one configuration per process and fail loudly instead of silently.

Property: a process never runs on a configuration it wasn't given, and never runs in production
with a message bus that drops events. Tests: a second, different configuration is refused (the
same one is a no-op); an unreachable broker stops a production process but degrades outside it;
each model alias is served by its own backend with its own connection settings.
"""

import logging
import threading
import time

import pytest

import k9_aif_abb.k9_core.messaging.k9_event_bus as bus_mod
from k9_aif_abb.k9_core.base_component import BaseComponent
from k9_aif_abb.k9_core.inference.base_provider_adapter import BaseProviderAdapter
from k9_aif_abb.k9_core.inference.provider_registry import ProviderAdapterRegistry
from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus
from k9_aif_abb.k9_core.messaging.messaging_errors import MessagingUnavailableError
from k9_aif_abb.k9_factories import reset_all
from k9_aif_abb.k9_factories.factory_errors import ConfigConflictError
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.message_factory import MessageFactory
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory


# ── helpers ──────────────────────────────────────────────────────────────

class _NoBroker(Exception):
    pass


def _unreachable_producer(*args, **kwargs):
    raise _NoBroker("NoBrokersAvailable")


@pytest.fixture
def no_broker(monkeypatch):
    """KafkaProducer that fails as it does when no broker answers (no network needed)."""
    monkeypatch.setattr(bus_mod, "KafkaProducer", _unreachable_producer)


def _kafka_config(**extra):
    return {"messaging": {"backend": "kafka", "brokers": ["broker.invalid:9092"], "topic": "acme-events",
                          "group_id": "acme-console", **extra}}


class _Recorder:
    """Records what each backend was asked to build."""
    calls = []


def _recording_adapter(name, delay=0.0):
    class _Adapter(BaseProviderAdapter):
        @property
        def provider_name(self):
            return name

        def create_llm(self, model_name, factory_cfg, extra_kwargs):
            time.sleep(delay)
            _Recorder.calls.append({"backend": name, "model": model_name, "cfg": dict(factory_cfg),
                                    "extra": dict(extra_kwargs)})
            return object()
    return _Adapter


@pytest.fixture
def backends(monkeypatch):
    _Recorder.calls = []
    monkeypatch.setitem(ProviderAdapterRegistry._adapters, "rec_local", _recording_adapter("rec_local"))
    monkeypatch.setitem(ProviderAdapterRegistry._adapters, "rec_cloud", _recording_adapter("rec_cloud"))
    return _Recorder


def _inference(models=None, backend="rec_local", catalog=None, **factory):
    inf = {"llm_factory": {"backend": backend, "base_url": "http://local:1", "models": models or {"general": "m1"},
                           **factory},
           "router": {"type": "k9", "persistence": {"enabled": False}}}
    if catalog is not None:
        inf["model_catalog"] = catalog
    return {"inference": inf}


# ── message bus: no silent loss in production ────────────────────────────

def test_event_bus_refuses_unreachable_broker_in_production(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    with pytest.raises(MessagingUnavailableError, match="cannot be reached"):
        K9EventBus(broker_url="broker.invalid:9092")


def test_event_bus_degrades_outside_production(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "development")
    bus = K9EventBus(broker_url="broker.invalid:9092")
    assert bus._producer is None


def test_event_bus_explicit_opt_out(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    bus = K9EventBus(broker_url="broker.invalid:9092", require_connection=False)
    assert bus._producer is None


def test_message_factory_refuses_in_production(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    with pytest.raises(MessagingUnavailableError):
        MessageFactory.create(_kafka_config())
    assert not MessageFactory.is_initialized()


def test_message_factory_falls_back_outside_production(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "test")
    bus = MessageFactory.create(_kafka_config())
    assert hasattr(bus, "publish") and hasattr(bus, "subscribe")      # a usable bus, not a bare queue
    bus.publish({"task_id": "t1", "x": 1})


def test_message_factory_fallback_allowed_explicitly_in_production(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    bus = MessageFactory.create(_kafka_config(allow_local_fallback=True))
    assert hasattr(bus, "publish")


def test_local_backend_needs_no_broker(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    bus = MessageFactory.create({"messaging": {"backend": "local"}})
    assert hasattr(bus, "publish")


def test_base_component_does_not_swallow_unreachable_bus(monkeypatch, no_broker):
    monkeypatch.setenv("K9_ENV", "production")
    with pytest.raises(MessagingUnavailableError):
        BaseComponent(config=_kafka_config())


def test_shared_default_names_are_warned(monkeypatch, no_broker, caplog):
    monkeypatch.setenv("K9_ENV", "test")
    with caplog.at_level(logging.WARNING, logger="MessageFactory"):
        MessageFactory.create({"messaging": {"backend": "kafka", "brokers": ["broker.invalid:9092"]}})
    assert "shared defaults" in caplog.text


def test_consumer_in_default_group_is_warned(monkeypatch, caplog):
    class _Producer:
        def __init__(self, *a, **k):
            pass

    def _consumer(*a, **k):
        raise _NoBroker("stop here")

    monkeypatch.setattr(bus_mod, "KafkaProducer", _Producer)
    monkeypatch.setattr(bus_mod, "KafkaConsumer", _consumer)
    bus = K9EventBus(broker_url="broker.invalid:9092", topic="t")
    with caplog.at_level(logging.WARNING, logger="K9EventBus"):
        bus.subscribe(lambda m: None)
    assert "default group" in caplog.text
    caplog.clear()
    named = K9EventBus(broker_url="broker.invalid:9092", topic="t", group_id="acme-router")
    with caplog.at_level(logging.WARNING, logger="K9EventBus"):
        named.subscribe(lambda m: None)
    assert "default group" not in caplog.text


# ── one configuration per process ────────────────────────────────────────

def test_llm_factory_same_config_twice_is_a_no_op(backends):
    cfg = _inference()
    LLMFactory.bootstrap(cfg)
    LLMFactory.bootstrap(cfg)
    LLMFactory.bootstrap({"llm_factory": cfg["inference"]["llm_factory"]})     # flattened form, same section


def test_llm_factory_refuses_a_different_config(backends):
    LLMFactory.bootstrap(_inference(models={"general": "m1"}))
    with pytest.raises(ConfigConflictError, match="one application per process"):
        LLMFactory.bootstrap(_inference(models={"general": "m2"}))


def test_config_without_inference_uses_what_is_set_up(backends):
    LLMFactory.bootstrap(_inference())
    LLMFactory.ensure_bootstrapped({"role": "Analyst", "goal": "an agent's own fields"})
    assert LLMFactory.get_model("general") == "m1"


def test_router_is_shared_by_configs_with_the_same_inference(backends):
    app = _inference()
    r1 = ModelRouterFactory.get_router(app)
    agent_cfg = {**app, "role": "Analyst", "goal": "summarize"}               # global + agent fields
    assert ModelRouterFactory.get_router(agent_cfg) is r1
    assert ModelRouterFactory.get_router({"role": "no inference section"}) is r1


def test_router_refuses_a_different_inference_config(backends):
    ModelRouterFactory.get_router(_inference())
    other = _inference()
    other["inference"]["router"]["default_model_alias"] = "elsewhere"
    with pytest.raises(ConfigConflictError):
        ModelRouterFactory.get_router(other)


def test_reset_all_allows_a_new_configuration(backends):
    ModelRouterFactory.get_router(_inference(models={"general": "m1"}))
    reset_all()
    ModelRouterFactory.get_router(_inference(models={"general": "m2"}))
    assert LLMFactory.get_model("general") == "m2"


# ── per-model backend ────────────────────────────────────────────────────

def test_each_alias_uses_its_own_backend_and_connection(backends):
    LLMFactory.bootstrap(_inference(models={
        "general": "local-model",
        "auditor": {"backend": "rec_cloud", "model": "cloud-model", "base_url": "https://cloud:443",
                    "temperature": 0.1},
    }))
    LLMFactory.get("general")
    LLMFactory.get("auditor")
    local, cloud = backends.calls
    assert (local["backend"], local["model"], local["cfg"]["base_url"]) == ("rec_local", "local-model", "http://local:1")
    assert (cloud["backend"], cloud["model"], cloud["cfg"]["base_url"]) == ("rec_cloud", "cloud-model", "https://cloud:443")
    assert cloud["extra"] == {"temperature": 0.1}                 # model params are not connection settings
    assert "models" not in cloud["cfg"]


def test_legacy_provider_key_on_alias_is_honoured(backends):
    LLMFactory.bootstrap(_inference(models={"general": {"provider": "rec_cloud", "model": "m"}}))
    assert LLMFactory.backend_for("general") == "rec_cloud"


def test_digest_pin_needs_ollama_for_that_alias(backends):
    LLMFactory.bootstrap(_inference(models={"pinned": {"backend": "rec_cloud", "model": "m", "digest": "sha256:ab"}}))
    with pytest.raises(ValueError, match="ollama backend only"):
        LLMFactory.get("pinned")


def test_catalog_provider_must_match_the_serving_backend(backends):
    catalog = {"default_model": "general",
               "models": {"general": {"provider": "rec_cloud", "llm_ref": "general", "capabilities": ["chat"]}}}
    with pytest.raises(ConfigConflictError, match="served by 'rec_local'"):
        ModelRouterFactory.get_router(_inference(catalog=catalog))


def test_catalog_provider_matching_per_alias_backend_is_accepted(backends):
    catalog = {"default_model": "general",
               "models": {"general": {"provider": "rec_local", "llm_ref": "general", "capabilities": ["chat"]},
                          "secure": {"provider": "rec_cloud", "llm_ref": "secure", "capabilities": ["confidential"]}}}
    ModelRouterFactory.get_router(_inference(
        models={"general": "m1", "secure": {"backend": "rec_cloud", "model": "m2"}}, catalog=catalog))


def test_concurrent_get_builds_one_instance(monkeypatch):
    _Recorder.calls = []
    monkeypatch.setitem(ProviderAdapterRegistry._adapters, "rec_slow", _recording_adapter("rec_slow", delay=0.05))
    LLMFactory.bootstrap(_inference(backend="rec_slow"))
    got = []
    threads = [threading.Thread(target=lambda: got.append(LLMFactory.get("general"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_Recorder.calls) == 1 and len({id(x) for x in got}) == 1
