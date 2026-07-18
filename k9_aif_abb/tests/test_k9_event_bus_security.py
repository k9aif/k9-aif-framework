# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tests for K9EventBus SASL/TLS support (G5).

Verifies the new security_protocol/sasl_mechanism options are opt-in,
backward compatible (PLAINTEXT unchanged), credentials come from environment
variables only, and MessageFactory threads the new config keys through.

Fully offline — KafkaProducer is mocked, no real broker needed.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus
from k9_aif_abb.k9_factories.message_factory import MessageFactory


@pytest.fixture(autouse=True)
def _reset_message_factory():
    MessageFactory.reset()
    yield
    MessageFactory.reset()


# ── _security_kwargs() ────────────────────────────────────────────────────────

def test_default_security_protocol_is_plaintext():
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = K9EventBus(broker_url="localhost:9092")
    assert bus.security_protocol == "PLAINTEXT"
    assert bus._security_kwargs() == {"security_protocol": "PLAINTEXT"}


def test_plaintext_kwargs_have_no_sasl_fields():
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = K9EventBus(broker_url="localhost:9092", security_protocol="PLAINTEXT")
    kwargs = bus._security_kwargs()
    assert "sasl_mechanism" not in kwargs
    assert "sasl_plain_username" not in kwargs


def test_sasl_ssl_kwargs_include_credentials_from_env(monkeypatch):
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "svc-account")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "secret-value")

    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = K9EventBus(
            broker_url="broker:9092",
            security_protocol="SASL_SSL",
            sasl_mechanism="SCRAM-SHA-256",
        )

    kwargs = bus._security_kwargs()
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "SCRAM-SHA-256"
    assert kwargs["sasl_plain_username"] == "svc-account"
    assert kwargs["sasl_plain_password"] == "secret-value"


def test_sasl_ssl_defaults_to_empty_credentials_when_env_unset(monkeypatch):
    monkeypatch.delenv("KAFKA_SASL_USERNAME", raising=False)
    monkeypatch.delenv("KAFKA_SASL_PASSWORD", raising=False)

    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = K9EventBus(broker_url="broker:9092", security_protocol="SASL_SSL")

    kwargs = bus._security_kwargs()
    assert kwargs["sasl_plain_username"] == ""
    assert kwargs["sasl_plain_password"] == ""


def test_producer_constructed_with_security_kwargs():
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer") as mock_producer_cls:
        K9EventBus(broker_url="broker:9092", security_protocol="SASL_SSL", sasl_mechanism="PLAIN")
    _, kwargs = mock_producer_cls.call_args
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "PLAIN"


def test_producer_constructed_plaintext_by_default():
    """Existing deployments that never set security_protocol get identical behavior to before."""
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer") as mock_producer_cls:
        K9EventBus(broker_url="broker:9092")
    _, kwargs = mock_producer_cls.call_args
    assert kwargs["security_protocol"] == "PLAINTEXT"
    assert "sasl_mechanism" not in kwargs


def test_producer_init_failure_still_degrades_gracefully():
    """A construction failure (e.g. broker unreachable) must not raise — _producer stays None."""
    with patch(
        "k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer",
        side_effect=Exception("connection refused"),
    ):
        bus = K9EventBus(broker_url="unreachable:9092")
    assert bus._producer is None


# ── MessageFactory threading ──────────────────────────────────────────────────

def test_message_factory_defaults_to_plaintext():
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = MessageFactory.create({"messaging": {"backend": "kafka", "brokers": ["broker:9092"]}})
    assert bus.security_protocol == "PLAINTEXT"


def test_message_factory_threads_sasl_config():
    cfg = {
        "messaging": {
            "backend": "kafka",
            "brokers": ["broker:9092"],
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "SCRAM-SHA-512",
        }
    }
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        bus = MessageFactory.create(cfg)
    assert bus.security_protocol == "SASL_SSL"
    assert bus.sasl_mechanism == "SCRAM-SHA-512"
