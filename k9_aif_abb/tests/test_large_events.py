# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Large events (1.20): an event over max_event_bytes is stored in object storage and sent as a link;
consumers get the original back. Before 1.20 it was replaced by {"truncated": true} and sent anyway,
and every send error was logged and dropped.

Offline: KafkaProducer/KafkaConsumer are mocked; object storage is an in-memory fake or local files.
"""

import hashlib
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus
from k9_aif_abb.k9_core.storage.base_object_storage import BaseObjectStorage

BUS = "k9_aif_abb.k9_core.messaging.k9_event_bus"


class FakeStore(BaseObjectStorage):
    def __init__(self, fail_upload=False, expiry=True):
        self.objects, self.buckets, self.expiry_calls = {}, [], []
        self.fail_upload, self.expiry = fail_upload, expiry

    def upload(self, bucket, key, data, metadata=None):
        if self.fail_upload:
            raise ConnectionError("store down")
        self.objects[(bucket, key)] = data
        return f"s3://{bucket}/{key}"

    def download(self, bucket, key):
        if (bucket, key) not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[(bucket, key)]

    def delete(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def list_objects(self, bucket, prefix=None):
        return [k for b, k in self.objects if b == bucket]

    def get_uri(self, bucket, key):
        return f"s3://{bucket}/{key}"

    def ensure_bucket(self, bucket):
        self.buckets.append(bucket)

    def set_expiry(self, bucket, prefix, days):
        self.expiry_calls.append((bucket, prefix, days))
        return self.expiry


def _bus(**kw):
    with patch(f"{BUS}.KafkaProducer") as producer_cls:
        bus = K9EventBus(broker_url="localhost:9092", topic="t", group_id="g", **kw)
    return bus, producer_cls.return_value


def _sent(producer):
    assert producer.send.call_count == 1
    return producer.send.call_args.kwargs["value"]


BIG = {"event_type": "doc.ready", "correlation_id": "c-1", "payload": {"text": "x" * (600 * 1024)}}


def test_large_event_is_stored_and_sent_as_link():
    store = FakeStore()
    bus, producer = _bus(object_store=store)
    bus.publish(BIG)
    sent = _sent(producer)
    ref = sent["k9_large_event"]
    assert "payload" not in sent and "truncated" not in json.dumps(sent)
    assert sent["event_type"] == "doc.ready" and sent["correlation_id"] == "c-1"
    assert ref["bucket"] == "k9aif-large-events" and ref["key"].startswith("large-events/t/")
    assert json.loads(store.objects[(ref["bucket"], ref["key"])]) == BIG
    assert ref["sha256"] == hashlib.sha256(store.objects[(ref["bucket"], ref["key"])]).hexdigest()


def test_publish_to_uses_the_same_path():
    store = FakeStore()
    bus, producer = _bus(object_store=store)
    bus.publish_to("hil.requests.claims", BIG)
    assert producer.send.call_args.args[0] == "hil.requests.claims"
    assert _sent(producer)["k9_large_event"]["key"].startswith("large-events/hil.requests.claims/")


def test_consumer_gets_the_original_event():
    store = FakeStore()
    bus, producer = _bus(object_store=store)
    bus.publish(BIG)
    link = _sent(producer)
    got = []
    with patch(f"{BUS}.KafkaConsumer", return_value=[SimpleNamespace(value=link)]):
        bus.subscribe(got.append)
    assert got == [BIG]


def test_small_events_are_unchanged():
    bus, producer = _bus(object_store=FakeStore())
    bus.publish({"event_type": "x", "n": 1})
    assert _sent(producer) == {"event_type": "x", "n": 1}


def test_default_bucket_created_with_30_day_expiry_on_prefix():
    store = FakeStore()
    bus, _ = _bus(object_store=store)
    bus.publish(BIG)
    bus.publish(BIG)
    assert store.buckets == ["k9aif-large-events"]
    assert store.expiry_calls == [("k9aif-large-events", "large-events/", 30)]


def test_bucket_and_ttl_from_config():
    store = FakeStore()
    bus, _ = _bus(object_store=store, config={"messaging": {"large_events": {"bucket": "acme-ev", "ttl_days": 0}}})
    bus.publish(BIG)
    assert store.buckets == ["acme-ev"] and store.expiry_calls == []


def test_store_without_expiry_support_is_reported(caplog):
    bus, _ = _bus(object_store=FakeStore(expiry=False))
    bus.publish(BIG)
    assert "will NOT expire" in caplog.text


def test_failed_upload_raises_and_nothing_is_sent():
    from k9_aif_abb.k9_core.messaging.messaging_errors import LargeEventError
    bus, producer = _bus(object_store=FakeStore(fail_upload=True))
    with pytest.raises(LargeEventError, match="was not sent"):
        bus.publish(BIG)
    producer.send.assert_not_called()


def test_production_without_object_storage_raises(monkeypatch):
    from k9_aif_abb.k9_core.messaging.messaging_errors import LargeEventError
    monkeypatch.setenv("K9_ENV", "production")
    bus, producer = _bus()
    with pytest.raises(LargeEventError, match="no object_storage"):
        bus.publish(BIG)
    producer.send.assert_not_called()


def test_development_without_object_storage_uses_local_files(monkeypatch, tmp_path):
    monkeypatch.setenv("K9_ENV", "development")
    monkeypatch.chdir(tmp_path)
    bus, producer = _bus()
    bus.publish(BIG)
    assert bus.resolve_event(_sent(producer)) == BIG


def test_tampered_or_missing_event_raises():
    from k9_aif_abb.k9_core.messaging.messaging_errors import LargeEventError
    store = FakeStore()
    bus, producer = _bus(object_store=store)
    bus.publish(BIG)
    link = _sent(producer)
    ref = link["k9_large_event"]
    store.objects[(ref["bucket"], ref["key"])] = b'{"payload": "changed"}'
    with pytest.raises(LargeEventError, match="hash"):
        bus.resolve_event(link)
    store.objects.clear()
    with pytest.raises(LargeEventError, match="could not be fetched"):
        bus.resolve_event(link)


def test_unfetchable_event_is_skipped_with_error_not_delivered(caplog):
    store = FakeStore()
    bus, producer = _bus(object_store=store)
    bus.publish(BIG)
    link = _sent(producer)
    store.objects.clear()
    got = []
    with patch(f"{BUS}.KafkaConsumer", return_value=[SimpleNamespace(value=link)]):
        bus.subscribe(got.append)
    assert got == [] and "event skipped" in caplog.text


def test_send_errors_reach_the_caller():
    bus, producer = _bus()
    producer.send.side_effect = RuntimeError("buffer full")
    with pytest.raises(RuntimeError, match="buffer full"):
        bus.publish({"event_type": "x"})
    with pytest.raises(RuntimeError, match="buffer full"):
        bus.publish_to("t2", {"event_type": "x"})


def test_message_factory_publish_uses_the_bus_and_raises():
    from k9_aif_abb.k9_factories.message_factory import MessageFactory
    bus = MagicMock()
    MessageFactory._singleton = bus
    try:
        MessageFactory.publish({"topic": "a.b", "event_type": "x"})
        bus.publish_to.assert_called_once_with("a.b", {"topic": "a.b", "event_type": "x"})
        bus.publish_to.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError, match="down"):
            MessageFactory.publish({"topic": "a.b"})
    finally:
        MessageFactory.reset()


# ── S3-API lifecycle helper ───────────────────────────────────────────────────

class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def test_set_expiry_keeps_existing_rules():
    from k9_aif_abb.k9_storage.adapters import s3_lifecycle
    client = MagicMock()
    other = {"ID": "keep-me", "Filter": {"Prefix": "logs/"}, "Status": "Enabled", "Expiration": {"Days": 7}}
    old = {"ID": "k9aif-expire-large-events", "Filter": {"Prefix": "large-events/"}, "Expiration": {"Days": 90}}
    client.get_bucket_lifecycle_configuration.return_value = {"Rules": [other, old]}
    assert s3_lifecycle.set_expiry(client, "b", "large-events/", 30)
    rules = client.put_bucket_lifecycle_configuration.call_args.kwargs["LifecycleConfiguration"]["Rules"]
    assert rules[0] == other and len(rules) == 2
    assert rules[1]["Expiration"] == {"Days": 30} and rules[1]["Filter"] == {"Prefix": "large-events/"}


def test_set_expiry_on_bucket_without_rules():
    from k9_aif_abb.k9_storage.adapters import s3_lifecycle
    client = MagicMock()
    client.get_bucket_lifecycle_configuration.side_effect = _ClientError("NoSuchLifecycleConfiguration")
    s3_lifecycle.set_expiry(client, "b", "large-events/", 30)
    assert len(client.put_bucket_lifecycle_configuration.call_args.kwargs["LifecycleConfiguration"]["Rules"]) == 1


def test_ensure_bucket_creates_missing_and_raises_on_other_errors():
    from k9_aif_abb.k9_storage.adapters import s3_lifecycle
    client = MagicMock()
    client.head_bucket.side_effect = _ClientError("404")
    s3_lifecycle.ensure_bucket(client, "b", "us-east-1")
    client.create_bucket.assert_called_once_with(Bucket="b")
    client = MagicMock()
    client.head_bucket.side_effect = _ClientError("403")
    with pytest.raises(_ClientError):
        s3_lifecycle.ensure_bucket(client, "b")
    client.create_bucket.assert_not_called()


def test_local_store_expiry_removes_old_files(tmp_path):
    from k9_aif_abb.k9_storage.adapters.local_adapter import LocalObjectStorageAdapter
    store = LocalObjectStorageAdapter({"object_storage": {"root": str(tmp_path)}})
    store.upload("b", "large-events/t/old.json", b"{}")
    store.upload("b", "large-events/t/new.json", b"{}")
    store.upload("b", "other/keep.json", b"{}")
    old = tmp_path / "b" / "large-events" / "t" / "old.json"
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    os.utime(tmp_path / "b" / "other" / "keep.json", (time.time() - 40 * 86400,) * 2)
    assert store.set_expiry("b", "large-events/", 30)
    assert sorted(store.list_objects("b")) == ["large-events/t/new.json", "other/keep.json"]
