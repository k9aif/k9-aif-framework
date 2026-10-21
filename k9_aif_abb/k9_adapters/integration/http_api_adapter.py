# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""HttpApiAdapter — built-in BaseApiAdapter for plain REST/JSON endpoints."""

from __future__ import annotations

from typing import Any, Dict

from .base_api_adapter import BaseApiAdapter
from .outbound_guard import check_destination, fill_url


class HttpApiAdapter(BaseApiAdapter):
    """
    REST/JSON over HTTP(S) with ``requests``. Config keys: ``url`` (may contain ``{name}``
    placeholders filled from the payload, e.g. ``https://erp/api/invoices/{id}``), ``method``
    (default POST; GET sends the payload as query parameters), ``headers``, ``timeout``
    (default 30). Credentials belong in headers built from environment variables, never in
    config.yaml.

    Outbound guard (1.18.5): payload values are URL-encoded into the placeholders, the destination is
    checked before the request and again on every redirect (``allowed_hosts``, ``allow_private_networks``;
    see outbound_guard.py).

    Registered as ``http`` in IntegrationAdapterFactory.
    """

    MAX_REDIRECTS = 5

    def call_endpoint(self, url: str, method: str, headers: Dict[str, str], body: Dict[str, Any]) -> Any:
        import requests
        from urllib.parse import urljoin, urlsplit
        fields = {k: v for k, v in body.items() if isinstance(v, (str, int, float))}
        target = fill_url(url, fields)               # placeholder values URL-encoded: never URL structure
        allowed = self.config.get("allowed_hosts")
        private_ok = self.destination_private_ok(url)
        timeout = float(self.config.get("timeout", 30))
        for _ in range(self.MAX_REDIRECTS + 1):
            check_destination(target, allowed_hosts=allowed, private_ok=private_ok)
            if method == "GET":
                resp = requests.get(target, headers=headers, params=body.get("params"), timeout=timeout,
                                    allow_redirects=False)
            else:
                resp = requests.request(method, target, headers=headers, json=body.get("json", body),
                                        timeout=timeout, allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                nxt = urljoin(target, resp.headers["Location"])      # every hop is checked again
                # The configured host's trust survives a redirect only on that same host.
                if urlsplit(nxt).hostname != urlsplit(target).hostname:
                    private_ok = bool(self.config.get("allow_private_networks"))
                target = nxt
                if resp.status_code == 303:
                    method = "GET"
                continue
            break
        else:
            raise RuntimeError(f"too many redirects (>{self.MAX_REDIRECTS})")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return resp.text
