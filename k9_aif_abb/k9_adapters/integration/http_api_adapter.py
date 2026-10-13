# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""HttpApiAdapter — built-in BaseApiAdapter for plain REST/JSON endpoints."""

from __future__ import annotations

from typing import Any, Dict

from .base_api_adapter import BaseApiAdapter


class HttpApiAdapter(BaseApiAdapter):
    """
    REST/JSON over HTTP(S) with ``requests``. Config keys: ``url`` (may contain ``{name}``
    placeholders filled from the payload, e.g. ``https://erp/api/invoices/{id}``), ``method``
    (default POST; GET sends the payload as query parameters), ``headers``, ``timeout``
    (default 30). Credentials belong in headers built from environment variables, never in
    config.yaml.

    Registered as ``http`` in IntegrationAdapterFactory.
    """

    def call_endpoint(self, url: str, method: str, headers: Dict[str, str], body: Dict[str, Any]) -> Any:
        import requests

        fields = {k: v for k, v in body.items() if isinstance(v, (str, int, float))}
        try:
            url = url.format(**fields)
        except (KeyError, IndexError):
            pass
        timeout = float(self.config.get("timeout", 30))
        if method == "GET":
            resp = requests.get(url, headers=headers, params=body.get("params"), timeout=timeout)
        else:
            resp = requests.request(method, url, headers=headers, json=body.get("json", body), timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return resp.text
