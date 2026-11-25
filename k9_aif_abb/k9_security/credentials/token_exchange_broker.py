# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
TokenExchangeCredentialBroker: OAuth 2.0 token exchange, RFC 8693 (1.36.0).

For each outbound call to an audience (an MCP server registered as a client in
the identity provider), the broker sends the provider's token endpoint:

- the caller's own token (``subject_token``), read from the subject token store;
- this application's client credentials (one client for the K9-AIF application);
- the audience it wants.

The provider checks its exchange policy and returns a short-lived token with
``aud`` = that audience, ``sub`` = the caller, ``azp`` = this application. The
MCP server validates it and decides from the caller's roles in it. Which agent
made the call is recorded here (log line + ``OnBehalfOf`` trace event), not in
the token: all agents share the application's client.

Exchanged tokens are cached per (caller token, audience) until shortly before
they expire. Any failure raises ``CredentialUnavailableError``; there is no
fallback to a shared key.

Config (``security.on_behalf_of``)::

    enabled: true
    broker: token_exchange
    token_endpoint: ${KEYCLOAK_URL}/realms/k9x/protocol/openid-connect/token
    client_id: k9-ap-app
    client_secret_env: K9_OBO_CLIENT_SECRET    # the secret itself lives in .env
    timeout: 10
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from k9_aif_abb.k9_core.identity.base_credential_broker import (
    BaseCredentialBroker,
    CredentialUnavailableError,
)
from k9_aif_abb.k9_core.identity.caller_context import CallerContext
from k9_aif_abb.k9_core.identity.subject_token_store import SubjectTokenStore

log = logging.getLogger("k9.on_behalf_of")

GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
_REFRESH_MARGIN_SECONDS = 30


def _post_form(url: str, form: Dict[str, str], timeout: float) -> Tuple[int, Dict[str, Any]]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"{}")
        except ValueError:
            body = {}
        return exc.code, body


class TokenExchangeCredentialBroker(BaseCredentialBroker):

    def __init__(self, token_endpoint: str, client_id: str, client_secret: str,
                 token_store: SubjectTokenStore, timeout: float = 10.0,
                 post: Optional[Callable[[str, Dict[str, str], float], Tuple[int, Dict[str, Any]]]] = None) -> None:
        """``post(url, form, timeout) -> (status, json)`` overrides the HTTP call (tests)."""
        if not token_endpoint:
            raise ValueError("TokenExchangeCredentialBroker needs token_endpoint")
        if not client_id or not client_secret:
            raise ValueError("TokenExchangeCredentialBroker needs client_id and a client secret "
                             "(security.on_behalf_of.client_secret_env)")
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self._client_secret = client_secret
        self.token_store = token_store
        self.timeout = float(timeout)
        self._post = post or _post_form
        self._cache: Dict[Tuple[str, str], Tuple[str, float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, cfg: Dict[str, Any], token_store: SubjectTokenStore) -> "TokenExchangeCredentialBroker":
        env_name = cfg.get("client_secret_env", "K9_OBO_CLIENT_SECRET")
        secret = os.environ.get(env_name, "")
        if not secret:
            raise ValueError(f"security.on_behalf_of: no client secret in ${env_name}")
        return cls(token_endpoint=cfg.get("token_endpoint", ""), client_id=cfg.get("client_id", ""),
                   client_secret=secret, token_store=token_store, timeout=cfg.get("timeout", 10))

    # ── BaseCredentialBroker ────────────────────────────────────────────────
    def headers_for(self, audience: str, caller: CallerContext, *,
                    agent: Optional[str] = None, connector: Optional[str] = None) -> Dict[str, str]:
        if not audience:
            raise CredentialUnavailableError("on_behalf_of needs an audience")
        if not caller.subject_token_ref:
            raise CredentialUnavailableError(
                f"no token to exchange for caller {caller.principal_id!r} (authenticated without a "
                "bearer token, or on_behalf_of was off when the request was admitted)")
        key = (caller.subject_token_ref, audience)
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
        if cached and cached[1] - _REFRESH_MARGIN_SECONDS > now:
            self._record(audience, caller, agent, connector, cached=True)
            return {"Authorization": f"Bearer {cached[0]}"}

        subject_token = self.token_store.get(caller.subject_token_ref)
        if not subject_token:
            raise CredentialUnavailableError(
                f"the token of caller {caller.principal_id!r} is no longer held (expired)")
        form = {
            "grant_type": GRANT_TYPE,
            "subject_token": subject_token,
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "requested_token_type": ACCESS_TOKEN_TYPE,
            "audience": audience,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
        }
        try:
            status, body = self._post(self.token_endpoint, form, self.timeout)
        except Exception as exc:  # unreachable provider: fail closed, never a shared key
            raise CredentialUnavailableError(
                f"token exchange for audience {audience!r} failed: identity provider unreachable ({exc})"
            ) from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if status != 200 or not token:
            reason = (body or {}).get("error_description") or (body or {}).get("error") or f"HTTP {status}"
            log.warning("[OnBehalfOf] exchange refused: caller=%s audience=%s agent=%s: %s",
                        caller.principal_id, audience, agent, reason)
            raise CredentialUnavailableError(
                f"token exchange for caller {caller.principal_id!r} and audience {audience!r} refused: {reason}")
        expires_in = int(body.get("expires_in") or 60)
        with self._lock:
            self._cache[key] = (token, now + expires_in)
        self._record(audience, caller, agent, connector, cached=False)
        return {"Authorization": f"Bearer {token}"}

    # ── audit ───────────────────────────────────────────────────────────────
    def _record(self, audience: str, caller: CallerContext, agent: Optional[str],
                connector: Optional[str], cached: bool) -> None:
        log.info("[OnBehalfOf] agent=%s acting for %s -> audience=%s via %s%s",
                 agent or "-", caller.principal_id, audience, connector or "-", " (cached)" if cached else "")
        try:
            from k9_aif_abb.k9_utils.trace_events import emit_trace_event
            emit_trace_event({"type": "OnBehalfOf", "agent": agent or "-", "principal": caller.principal_id,
                              "principal_type": caller.principal_type, "audience": audience,
                              "connector": connector, "request_id": caller.request_id, "cached": cached})
        except Exception as exc:  # tracing is best-effort; the log line above is the record
            log.debug("[OnBehalfOf] trace event not emitted: %s", exc)
