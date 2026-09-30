# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
OIDCAuthenticator — BaseAuthenticator for OpenID Connect bearer tokens.

Validates a JWT access token issued by an OIDC provider (Keycloak, Microsoft
Entra ID, Okta, IBM Security Verify, ...) and turns it into the
IdentityContext that BaseRouter.admit() signs for Zero Trust downstream:

  - signature verified against the provider's published keys (JWKS);
  - issuer must match; audience checked when configured; expiry enforced;
  - roles read from a configurable claim path (Keycloak: realm_access.roles);
  - principal_type "agent" for machine identities (Keycloak client-credentials
    service accounts, "service-account-*"), otherwise "user" — the non-human
    identities Zscaler ThreatLabz 2026 says must be authenticated like people.

Config (``security.auth.oidc``)::

    issuer:      http://keycloak-host:8113/realms/k9x     # required
    audience:    k9x-agents                               # optional (verified when set)
    jwks_uri:    <issuer>/protocol/openid-connect/certs   # default: Keycloak's path
    roles_claim: realm_access.roles                       # dotted path in the token
    tenant_claim: tenant                                  # optional
    leeway_seconds: 30                                    # clock skew allowance

Credentials passed to admit(): ``{"bearer_token": "<jwt>"}`` or
``{"authorization": "Bearer <jwt>"}``. Needs PyJWT with crypto:
``pip install "k9-aif[oidc]"``. Any invalid token returns None (never raises),
so admit() treats the caller as unauthenticated -> anonymous.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .context import IdentityContext
from .identity import BaseAuthenticator

log = logging.getLogger("governance.zero_trust.oidc")

_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384"]


class OIDCAuthenticator(BaseAuthenticator):

    def __init__(self, issuer: str, audience: Optional[str] = None, jwks_uri: Optional[str] = None,
                 roles_claim: str = "realm_access.roles", tenant_claim: Optional[str] = None,
                 leeway_seconds: int = 30,
                 key_resolver: Optional[Callable[[str], Any]] = None,
                 discovery: bool = False) -> None:
        """``key_resolver(token) -> key`` overrides JWKS lookup (tests, pinned keys).
        ``discovery=True`` reads jwks_uri from ``<issuer>/.well-known/openid-configuration``
        on first use (and refuses a document whose issuer doesn't match)."""
        if not issuer:
            raise ValueError("OIDCAuthenticator needs an issuer")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.discovery = bool(discovery) and not jwks_uri
        self.jwks_uri = jwks_uri or ("" if self.discovery else f"{self.issuer}/protocol/openid-connect/certs")
        self.roles_claim = roles_claim
        self.tenant_claim = tenant_claim
        self.leeway = int(leeway_seconds)
        self._key_resolver = key_resolver
        self._jwks_client = None
        try:
            import jwt  # noqa: F401
        except ImportError as exc:
            raise ImportError('OIDCAuthenticator needs PyJWT: pip install "k9-aif[oidc]"') from exc

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "OIDCAuthenticator":
        return cls(issuer=cfg.get("issuer", ""), audience=cfg.get("audience"), jwks_uri=cfg.get("jwks_uri"),
                   roles_claim=cfg.get("roles_claim", "realm_access.roles"),
                   tenant_claim=cfg.get("tenant_claim"), leeway_seconds=cfg.get("leeway_seconds", 30),
                   discovery=cfg.get("discovery", False))

    # ── BaseAuthenticator contract ────────────────────────────────────────────
    def authenticate(self, credentials: Dict[str, Any]) -> Optional[IdentityContext]:
        token = _bearer(credentials)
        if not token:
            return None
        claims = self._verify(token)
        if claims is None:
            return None
        principal_id, principal_type = self.principal(claims)
        return IdentityContext(
            principal_id=principal_id,
            principal_type=principal_type,
            roles=self.roles(claims),
            tenant_id=_dig(claims, self.tenant_claim) if self.tenant_claim else None,
        )

    # ── provider-specific pieces (IdP adapters override these) ───────────────
    def principal(self, claims: Dict[str, Any]) -> Tuple[str, str]:
        """(principal_id, principal_type). Default: Keycloak-style service accounts are agents."""
        username = claims.get("preferred_username") or claims.get("sub", "")
        if username.startswith("service-account-"):
            return username[len("service-account-"):], "agent"
        return username, "agent" if claims.get("typ") == "service" else "user"

    def roles(self, claims: Dict[str, Any]) -> List[str]:
        return _as_list(_dig(claims, self.roles_claim))

    # ── verification ─────────────────────────────────────────────────────────
    def _verify(self, token: str) -> Optional[Dict[str, Any]]:
        import jwt
        try:
            key = self._key_resolver(token) if self._key_resolver else self._jwks().get_signing_key_from_jwt(token).key
            return jwt.decode(
                token, key, algorithms=_ALGORITHMS, issuer=self.issuer,
                audience=self.audience, leeway=self.leeway,
                options={"verify_aud": bool(self.audience), "require": ["exp", "iat", "iss"]},
            )
        except Exception as exc:  # any failure = not authenticated, never an exception to the caller
            log.warning("[OIDCAuthenticator] token rejected: %s", str(exc)[:200])
            return None

    def _jwks(self):
        if self._jwks_client is None:
            import jwt
            if not self.jwks_uri:
                self.jwks_uri = self._discover_jwks_uri()
            self._jwks_client = jwt.PyJWKClient(self.jwks_uri, cache_keys=True, lifespan=300)
        return self._jwks_client

    def _discover_jwks_uri(self) -> str:
        """OIDC discovery. The document's issuer must equal ours: a mismatch
        means a misconfiguration or a spoofed endpoint, and is refused."""
        import json
        import urllib.request
        url = f"{self.issuer}/.well-known/openid-configuration"
        with urllib.request.urlopen(url, timeout=10) as resp:
            doc = json.loads(resp.read())
        if str(doc.get("issuer", "")).rstrip("/") != self.issuer:
            raise ValueError(f"OIDC discovery issuer {doc.get('issuer')!r} does not match {self.issuer!r}")
        return doc["jwks_uri"]


def _bearer(credentials: Dict[str, Any]) -> str:
    creds = credentials or {}
    token = creds.get("bearer_token") or ""
    header = creds.get("authorization") or creds.get("Authorization") or ""
    if not token and header.lower().startswith("bearer "):
        token = header[7:]
    return token.strip()


def _dig(claims: Dict[str, Any], path: Optional[str]) -> Any:
    value: Any = claims
    for part in (path or "").split("."):
        if not part:
            continue
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []
