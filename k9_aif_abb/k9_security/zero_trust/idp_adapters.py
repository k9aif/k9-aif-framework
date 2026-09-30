# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Identity-provider adapters: OOB BaseAuthenticator SBBs for specific IdPs.

Each is a thin preset over OIDCAuthenticator that knows its provider's
issuer / key-set URLs, where roles live in the token, and how a machine
(service account / app) identity is marked, so a solution configures a
provider name and a few values instead of every OIDC detail. Registered in
AuthenticatorFactory as "keycloak", "entra_id" and "okta"; any other OIDC
provider uses "oidc" (with ``discovery: true``).

    keycloak   issuer = <base_url>/realms/<realm>
               roles  = realm_access.roles + resource_access.<client_id>.roles
               agent  = service account (preferred_username "service-account-<client>")
    entra_id   issuer = https://login.microsoftonline.com/<tenant_id>/v2.0
               roles  = "roles" (app roles); audience required
               agent  = app-only token (idtyp "app")
    okta       issuer = https://<domain>/oauth2/<authorization_server>
               roles  = "groups" (needs a groups claim configured in Okta)
               agent  = client-credentials token (sub == cid)

Tokens are verified exactly as OIDCAuthenticator does (JWKS signature,
issuer, expiry, audience when set); invalid -> None, never an exception.
Needs ``pip install "k9-aif[oidc]"``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .oidc_authenticator import OIDCAuthenticator, _as_list, _dig


class KeycloakAuthenticator(OIDCAuthenticator):
    """Keycloak (the federal-program default IdP): realm AND client roles.

    Client roles are read only for the configured ``client_id`` — a role on
    some other client in the realm grants nothing here."""

    def __init__(self, base_url: Optional[str] = None, realm: Optional[str] = None,
                 client_id: Optional[str] = None, issuer: Optional[str] = None, **kwargs: Any) -> None:
        if not issuer:
            if not (base_url and realm):
                raise ValueError("KeycloakAuthenticator needs issuer, or base_url + realm")
            issuer = f"{base_url.rstrip('/')}/realms/{realm}"
        kwargs.setdefault("jwks_uri", f"{issuer.rstrip('/')}/protocol/openid-connect/certs")
        super().__init__(issuer=issuer, roles_claim="realm_access.roles", **kwargs)
        self.client_id = client_id

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "KeycloakAuthenticator":
        return cls(base_url=cfg.get("base_url"), realm=cfg.get("realm"), client_id=cfg.get("client_id"),
                   issuer=cfg.get("issuer"), audience=cfg.get("audience"),
                   tenant_claim=cfg.get("tenant_claim"), leeway_seconds=cfg.get("leeway_seconds", 30))

    def roles(self, claims: Dict[str, Any]) -> List[str]:
        found = _as_list(_dig(claims, "realm_access.roles"))
        if self.client_id:
            client = (claims.get("resource_access") or {}).get(self.client_id) or {}
            found += [r for r in _as_list(client.get("roles")) if r not in found]
        return found


class EntraIDAuthenticator(OIDCAuthenticator):
    """Microsoft Entra ID (v2.0 tokens). App roles in "roles"; audience is
    required (your API's application ID or App ID URI)."""

    def __init__(self, tenant_id: str, audience: str, **kwargs: Any) -> None:
        if not (tenant_id and audience):
            raise ValueError("EntraIDAuthenticator needs tenant_id and audience")
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        kwargs.setdefault("jwks_uri", f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")
        kwargs.setdefault("tenant_claim", "tid")
        super().__init__(issuer=issuer, audience=audience, roles_claim="roles", **kwargs)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "EntraIDAuthenticator":
        return cls(tenant_id=cfg.get("tenant_id", ""), audience=cfg.get("audience", ""),
                   tenant_claim=cfg.get("tenant_claim", "tid"), leeway_seconds=cfg.get("leeway_seconds", 30))

    def principal(self, claims: Dict[str, Any]) -> Tuple[str, str]:
        if claims.get("idtyp") == "app":
            return claims.get("azp") or claims.get("appid") or claims.get("sub", ""), "agent"
        return claims.get("preferred_username") or claims.get("upn") or claims.get("oid", ""), "user"


class OktaAuthenticator(OIDCAuthenticator):
    """Okta custom authorization server. Roles from "groups" (add a groups
    claim to the authorization server in Okta)."""

    def __init__(self, domain: str, authorization_server: str = "default",
                 audience: Optional[str] = "api://default", **kwargs: Any) -> None:
        if not domain:
            raise ValueError("OktaAuthenticator needs domain (e.g. yourorg.okta.com)")
        host = domain.replace("https://", "").rstrip("/")
        issuer = f"https://{host}/oauth2/{authorization_server}"
        kwargs.setdefault("jwks_uri", f"{issuer}/v1/keys")
        kwargs.setdefault("roles_claim", "groups")
        super().__init__(issuer=issuer, audience=audience, **kwargs)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "OktaAuthenticator":
        return cls(domain=cfg.get("domain", ""), authorization_server=cfg.get("authorization_server", "default"),
                   audience=cfg.get("audience", "api://default"), roles_claim=cfg.get("roles_claim", "groups"),
                   tenant_claim=cfg.get("tenant_claim"), leeway_seconds=cfg.get("leeway_seconds", 30))

    def principal(self, claims: Dict[str, Any]) -> Tuple[str, str]:
        if claims.get("cid") and claims.get("sub") == claims.get("cid"):
            return claims["cid"], "agent"
        return claims.get("sub", ""), "user"
