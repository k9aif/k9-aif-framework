# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Outbound guard (1.18.5): an agent cannot steer an API adapter's request to a metadata endpoint, an internal
host or another domain. K9X Sentinel finding #1170 (agents reaching external and internal hosts). Offline:
IP literals and a mocked requests module."""

import types

import pytest

from k9_aif_abb.k9_adapters.integration.http_api_adapter import HttpApiAdapter
from k9_aif_abb.k9_adapters.integration.outbound_guard import (OutboundRefused, check_destination, fill_url,
                                                               host_is_templated)


class _Resp:
    def __init__(self, status=200, location=None, body=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self._body = body if body is not None else {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


@pytest.fixture
def http(monkeypatch):
    """Fake `requests`: records each URL called; `script` maps a URL to the response it returns."""
    calls, script = [], {}

    def request(method, url, **kw):
        assert kw.get("allow_redirects") is False, "redirects must be followed by the guard, not by requests"
        calls.append(url)
        return script.get(url, _Resp())

    fake = types.SimpleNamespace(get=lambda url, **kw: request("GET", url, **kw), request=request)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake)
    return calls, script


def test_placeholder_values_cannot_change_the_url_structure():
    assert fill_url("https://erp.example.com/api/invoices/{id}", {"id": "../../admin?x=1#@evil.com"}) == \
        "https://erp.example.com/api/invoices/..%2F..%2Fadmin%3Fx%3D1%23%40evil.com"
    assert fill_url("https://h/{a}/{missing}", {"a": 7}) == "https://h/7/{missing}"
    assert host_is_templated("https://{tenant}.example.com/x") and not host_is_templated("https://h/{id}")


def test_metadata_and_link_local_addresses_are_always_refused():
    for url in ("http://169.254.169.254/latest/meta-data/iam/security-credentials/",
                "http://[fd00:ec2::254]/latest/meta-data/", "http://100.100.100.200/latest/meta-data/",
                "http://0.0.0.0:8080/", "http://[fe80::1]/"):
        with pytest.raises(OutboundRefused):
            check_destination(url, private_ok=True, allowed_hosts=None)


def test_agent_chosen_url_cannot_reach_internal_hosts(http):
    calls, _ = http
    adapter = HttpApiAdapter({"method": "GET"})                  # no url configured: the agent supplies it
    for url in ("http://10.0.0.5/admin", "http://127.0.0.1:8080/", "http://192.168.1.10/"):
        with pytest.raises(OutboundRefused):
            adapter.execute({"url": url})
    assert calls == []                                           # refused before any request left
    out = adapter.execute({"url": "https://93.184.216.34/data"})  # a public address is fine
    assert out["status"] == "success" and calls == ["https://93.184.216.34/data"]


def test_configured_internal_host_still_works_and_allowed_hosts_restricts(http):
    calls, _ = http
    erp = HttpApiAdapter({"url": "http://10.1.2.3/api/invoices/{id}", "method": "GET"})
    assert erp.execute({"id": "42"})["status"] == "success"       # the architect chose this internal host
    assert calls[-1] == "http://10.1.2.3/api/invoices/42"
    pinned = HttpApiAdapter({"method": "GET", "allowed_hosts": ["*.example.com"]})
    with pytest.raises(OutboundRefused):
        pinned.execute({"url": "https://93.184.216.34/"})       # public, but not on the list
    templated = HttpApiAdapter({"url": "http://{host}/x", "method": "GET"})
    with pytest.raises(OutboundRefused):
        templated.execute({"host": "10.0.0.9"})                   # the agent picks the host: internal refused


def test_every_redirect_hop_is_checked(http):
    calls, script = http
    adapter = HttpApiAdapter({"url": "https://93.184.216.34/start", "method": "GET"})
    script["https://93.184.216.34/start"] = _Resp(302, location="http://169.254.169.254/latest/meta-data/")
    with pytest.raises(OutboundRefused):
        adapter.execute({})
    assert calls == ["https://93.184.216.34/start"]               # the metadata hop was never requested
    script["https://93.184.216.34/start"] = _Resp(302, location="/next")
    script["https://93.184.216.34/next"] = _Resp(200, body={"done": 1})
    assert adapter.execute({})["result"] == {"done": 1}           # an ordinary same-host redirect works
