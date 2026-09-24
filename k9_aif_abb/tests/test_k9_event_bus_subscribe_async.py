# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tests for K9EventBus.subscribe_async() -- G-19.

A prior version called AIOKafkaConsumer(pattern=re.compile(pattern), ...),
which raises TypeError against a real broker on every aiokafka version --
that constructor has no `pattern` parameter; pattern subscription is
`consumer.subscribe(pattern=...)`, called after construction. Missed by
this framework's own test_hil_roundtrip.py, which fakes the message bus
entirely and never exercises this method's real aiokafka call -- caught
only by a live-integration test against a real broker. These tests use a
stub AIOKafkaConsumer that records exactly what it was constructed with
and what it was told to subscribe to, so a regression back to the
constructor-kwarg form fails immediately without needing live Kafka.
"""

import asyncio
from unittest.mock import patch

import pytest

from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus


class _StubAIOKafkaConsumer:
    """Records constructor kwargs and subscribe() calls; yields a fixed
    (possibly empty) list of fake messages then stops, so the `async for`
    loop in subscribe_async() terminates on its own instead of running
    forever."""

    last_instance = None

    def __init__(self, messages=None, **kwargs):
        self.kwargs = kwargs
        self.subscribe_calls = []
        self.started = False
        self.stopped = False
        self._messages = iter(messages or [])
        _StubAIOKafkaConsumer.last_instance = self

    def subscribe(self, **kwargs):
        self.subscribe_calls.append(kwargs)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration


class _FakeMsg:
    def __init__(self, value):
        self.value = value


def _make_stub_factory(messages=None):
    """AIOKafkaConsumer is called as AIOKafkaConsumer(**kwargs) in the
    fixed implementation (no positional topics/pattern args) -- this
    factory matches that call shape while still letting each test
    control what messages the loop yields."""
    def factory(**kwargs):
        return _StubAIOKafkaConsumer(messages=messages, **kwargs)
    return factory


def _make_bus():
    with patch("k9_aif_abb.k9_core.messaging.k9_event_bus.KafkaProducer"):
        return K9EventBus(broker_url="broker:9092", topic="default.topic", group_id="grp")


class TestSubscribeAsyncPattern:

    @pytest.mark.asyncio
    async def test_pattern_never_passed_to_constructor(self):
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(callback=lambda m: None, pattern=r"hil\..*")

        stub = _StubAIOKafkaConsumer.last_instance
        assert "pattern" not in stub.kwargs
        assert "topics" not in stub.kwargs

    @pytest.mark.asyncio
    async def test_pattern_subscription_called_after_construction(self):
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(callback=lambda m: None, pattern=r"hil\..*")

        stub = _StubAIOKafkaConsumer.last_instance
        assert stub.subscribe_calls == [{"pattern": r"hil\..*"}]
        assert stub.started
        assert stub.stopped

    @pytest.mark.asyncio
    async def test_short_metadata_max_age_ms_default(self):
        """aiokafka's own default (5 minutes) delays discovering a topic
        created after this consumer started -- must default to something
        in the 1-5s range, not aiokafka's default, and must be
        configurable, not hardcoded."""
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(callback=lambda m: None, pattern=r"hil\..*")

        stub = _StubAIOKafkaConsumer.last_instance
        assert 1000 <= stub.kwargs["metadata_max_age_ms"] <= 5000

    @pytest.mark.asyncio
    async def test_metadata_max_age_ms_configurable(self):
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(
                callback=lambda m: None, pattern=r"hil\..*", metadata_max_age_ms=2500,
            )

        stub = _StubAIOKafkaConsumer.last_instance
        assert stub.kwargs["metadata_max_age_ms"] == 2500


class TestSubscribeAsyncTopics:

    @pytest.mark.asyncio
    async def test_explicit_topics_subscribed(self):
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(callback=lambda m: None, topics=["a.in", "b.in"])

        stub = _StubAIOKafkaConsumer.last_instance
        assert stub.subscribe_calls == [{"topics": ["a.in", "b.in"]}]

    @pytest.mark.asyncio
    async def test_default_topic_used_when_neither_given(self):
        bus = _make_bus()
        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory()):
            await bus.subscribe_async(callback=lambda m: None)

        stub = _StubAIOKafkaConsumer.last_instance
        assert stub.subscribe_calls == [{"topics": ["default.topic"]}]


class TestSubscribeAsyncCallbackBehavior:

    @pytest.mark.asyncio
    async def test_sync_callback_invoked_with_decoded_value(self):
        bus = _make_bus()
        received = []
        with patch("aiokafka.AIOKafkaConsumer",
                    side_effect=_make_stub_factory(messages=[_FakeMsg({"correlation_id": "c1"})])):
            await bus.subscribe_async(callback=received.append, pattern=r"hil\..*")

        assert received == [{"correlation_id": "c1"}]

    @pytest.mark.asyncio
    async def test_async_callback_invoked_and_awaited(self):
        bus = _make_bus()
        received = []

        async def async_callback(value):
            received.append(value)

        with patch("aiokafka.AIOKafkaConsumer",
                    side_effect=_make_stub_factory(messages=[_FakeMsg({"correlation_id": "c2"})])):
            await bus.subscribe_async(callback=async_callback, pattern=r"hil\..*")

        assert received == [{"correlation_id": "c2"}]

    @pytest.mark.asyncio
    async def test_callback_error_on_one_message_does_not_stop_the_loop(self):
        bus = _make_bus()
        received = []

        def flaky_callback(value):
            if value.get("bad"):
                raise ValueError("boom")
            received.append(value)

        with patch("aiokafka.AIOKafkaConsumer", side_effect=_make_stub_factory(messages=[
            _FakeMsg({"bad": True}), _FakeMsg({"correlation_id": "c3"}),
        ])):
            await bus.subscribe_async(callback=flaky_callback, pattern=r"hil\..*")

        assert received == [{"correlation_id": "c3"}]
