# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/authenticator_factory.py

"""
AuthenticatorFactory — static factory for caller authentication (BaseAuthenticator).

Used by ``BaseRouter.admit()`` (through ``build_authenticator``) to verify who
is calling before a signed identity is stamped for Zero Trust downstream.

Pre-registered (OOB):
    api_key    ApiKeyAuthenticator     one key per principal, keys from env
    oidc       OIDCAuthenticator       any OpenID Connect provider (discovery: true)
    keycloak   KeycloakAuthenticator   realm + client roles, service accounts = agents
    entra_id   EntraIDAuthenticator    Microsoft Entra ID app roles
    okta       OktaAuthenticator       Okta custom authorization server, groups

A solution adds its own (a SAML bridge, a CAC/PIV-specific check, ...) by
extending BaseAuthenticator and registering it — exactly like any other
K9-AIF factory::

    AuthenticatorFactory.register("my_idp", MyAuthenticator)   # needs from_config(cfg)

YAML config::

    security:
      auth:
        providers:                       # tried in order; first identity wins
          - type: keycloak
            base_url: "${KEYCLOAK_URL:-http://localhost:8113}"
            realm: k9x
            client_id: k9x-agents        # client roles read for this client only
          - type: api_key
            api_keys:
              claims-bot: {env: K9_KEY_CLAIMS_BOT, principal_type: agent, roles: [claims_approver]}

The earlier shape (``security.auth.oidc: {...}`` / ``security.auth.api_keys: {...}``)
still works and maps to ``oidc`` / ``api_key``.

Usage::

    from k9_aif_abb.k9_factories.authenticator_factory import AuthenticatorFactory
    auth = AuthenticatorFactory.create(config)          # None when nothing is configured
    identity = auth.authenticate({"bearer_token": token})
"""

from threading import Lock
from typing import Any, Dict, List, Optional, Type
import logging

log = logging.getLogger("AuthenticatorFactory")


class AuthenticatorFactory:
    """Static Factory — provisions BaseAuthenticator implementations."""

    _registry: Dict[str, Type[Any]] = {}
    _lock = Lock()
    _bootstrapped = False

    def __init__(self, *args, **kwargs):
        raise RuntimeError("AuthenticatorFactory is static and cannot be instantiated")

    @staticmethod
    def _ensure_defaults() -> None:
        if AuthenticatorFactory._bootstrapped:
            return
        with AuthenticatorFactory._lock:
            if AuthenticatorFactory._bootstrapped:
                return
            from k9_aif_abb.k9_security.zero_trust.identity import ApiKeyAuthenticator
            # OIDC-based adapters are registered by import path and imported
            # only when used, so PyJWT stays an optional extra (k9-aif[oidc]).
            AuthenticatorFactory._registry.update({
                "api_key":  ApiKeyAuthenticator,
                "oidc":     "k9_aif_abb.k9_security.zero_trust.oidc_authenticator:OIDCAuthenticator",
                "keycloak": "k9_aif_abb.k9_security.zero_trust.idp_adapters:KeycloakAuthenticator",
                "entra_id": "k9_aif_abb.k9_security.zero_trust.idp_adapters:EntraIDAuthenticator",
                "okta":     "k9_aif_abb.k9_security.zero_trust.idp_adapters:OktaAuthenticator",
            })
            AuthenticatorFactory._bootstrapped = True
            log.info("[Factory] Bootstrapped AuthenticatorFactory")

    @staticmethod
    def register(name: str, cls: Type[Any]) -> None:
        """Register a custom BaseAuthenticator (it needs a ``from_config(cfg)`` classmethod,
        or a constructor taking the provider's config keys)."""
        AuthenticatorFactory._ensure_defaults()
        with AuthenticatorFactory._lock:
            AuthenticatorFactory._registry[name.lower()] = cls
            log.debug("[Factory] Registered authenticator '%s'", name)

    @staticmethod
    def available() -> List[str]:
        AuthenticatorFactory._ensure_defaults()
        return sorted(AuthenticatorFactory._registry)

    @staticmethod
    def get(name: str, provider_config: Optional[Dict[str, Any]] = None):
        """An authenticator of the named type, built from one provider's config block."""
        AuthenticatorFactory._ensure_defaults()
        entry = AuthenticatorFactory._registry.get((name or "").lower())
        if entry is None:
            raise ValueError(f"Unknown authenticator type: {name!r}. "
                             f"Available: {AuthenticatorFactory.available()}")
        cls = _resolve(entry)
        cfg = dict(provider_config or {})
        cfg.pop("type", None)
        if name.lower() == "api_key":
            return cls(cfg.get("api_keys", cfg))
        if hasattr(cls, "from_config"):
            return cls.from_config(cfg)
        return cls(**cfg)

    @staticmethod
    def create(config: Optional[Dict[str, Any]] = None):
        """From ``security.auth``. One provider -> that authenticator; several ->
        ChainedAuthenticator (tried in order); none -> None."""
        auth_cfg = (((config or {}).get("security", {}) or {}).get("auth", {}) or {})
        blocks = list(auth_cfg.get("providers") or [])
        if auth_cfg.get("oidc"):                       # earlier shape, still supported
            blocks.append({"type": "oidc", **auth_cfg["oidc"]})
        if auth_cfg.get("api_keys"):
            blocks.append({"type": "api_key", "api_keys": auth_cfg["api_keys"]})
        built = [AuthenticatorFactory.get(b.get("type", ""), b) for b in blocks]
        if not built:
            return None
        if len(built) == 1:
            return built[0]
        from k9_aif_abb.k9_security.zero_trust.identity import ChainedAuthenticator
        return ChainedAuthenticator(*built)


def _resolve(entry: Any) -> Type[Any]:
    if not isinstance(entry, str):
        return entry
    module_name, class_name = entry.split(":")
    import importlib
    return getattr(importlib.import_module(module_name), class_name)
