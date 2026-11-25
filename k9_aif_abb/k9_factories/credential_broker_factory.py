# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
CredentialBrokerFactory: acting for the caller on outbound calls (1.36.0, opt-in).

Holds, for this process, the subject token store (where ``BaseRouter.admit()``
keeps the caller's token) and the ``BaseCredentialBroker`` that connectors ask
for per-call credentials. Configured from ``security.on_behalf_of`` by
``BaseRouter`` and ``BaseOrchestrator`` when they are built; one configuration
per process, a different one raises ``ConfigConflictError``.

Config::

    security:
      identity: {mode: signed}          # required: only a verified caller is acted for
      on_behalf_of:
        enabled: true
        broker: token_exchange          # OOB; register() your own
        token_endpoint: ${KEYCLOAK_URL}/realms/k9x/protocol/openid-connect/token
        client_id: k9-ap-app
        client_secret_env: K9_OBO_CLIENT_SECRET
        token_store: {provider: in_memory}   # redis when router and orchestrator are separate processes

A connector opts in with ``on_behalf_of: {audience: <client id of the server>}``
in its own config (``kwargs`` or top level).
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any, Dict, Optional, Type

from k9_aif_abb.k9_core.identity.base_credential_broker import (
    BaseCredentialBroker,
    CredentialUnavailableError,
)
from k9_aif_abb.k9_core.identity.caller_context import current_agent, current_caller
from k9_aif_abb.k9_core.identity.subject_token_store import SubjectTokenStore
from k9_aif_abb.k9_factories.factory_errors import ConfigConflictError
from k9_aif_abb.k9_utils.config_flags import config_flag

log = logging.getLogger("CredentialBrokerFactory")


def on_behalf_of_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The ``security.on_behalf_of`` block when enabled, else {}."""
    block = (((config or {}).get("security") or {}).get("on_behalf_of") or {})
    return dict(block) if config_flag(block.get("enabled"), False) else {}


class CredentialBrokerFactory:
    """Static factory: the process's subject token store and credential broker."""

    _registry: Dict[str, Type[BaseCredentialBroker]] = {}
    _lock = Lock()
    _config: Optional[Dict[str, Any]] = None
    _store: Optional[SubjectTokenStore] = None
    _broker: Optional[BaseCredentialBroker] = None

    def __init__(self, *args, **kwargs):
        raise RuntimeError("CredentialBrokerFactory is static and cannot be instantiated")

    @staticmethod
    def register(name: str, cls: Type[BaseCredentialBroker]) -> None:
        """A solution's own broker: ``cls.from_config(cfg, token_store)`` builds it."""
        with CredentialBrokerFactory._lock:
            CredentialBrokerFactory._registry[name.lower()] = cls

    @staticmethod
    def _class_for(name: str) -> Type[BaseCredentialBroker]:
        if name == "token_exchange" and name not in CredentialBrokerFactory._registry:
            from k9_aif_abb.k9_security.credentials.token_exchange_broker import TokenExchangeCredentialBroker
            CredentialBrokerFactory._registry["token_exchange"] = TokenExchangeCredentialBroker
        cls = CredentialBrokerFactory._registry.get(name)
        if cls is None:
            raise ValueError(f"security.on_behalf_of.broker: unknown broker {name!r}")
        return cls

    @staticmethod
    def configure(config: Optional[Dict[str, Any]]) -> bool:
        """Set up from ``security.on_behalf_of``. Returns whether it is enabled.
        Enabled requires ``security.identity.mode: signed``."""
        cfg = on_behalf_of_config(config)
        if not cfg:
            return False
        mode = str((((config or {}).get("security") or {}).get("identity") or {}).get("mode", "payload")).lower()
        if mode != "signed":
            raise ValueError("security.on_behalf_of needs security.identity.mode: signed "
                             "(the framework acts only for a verified caller)")
        with CredentialBrokerFactory._lock:
            if CredentialBrokerFactory._config is not None:
                if CredentialBrokerFactory._config != cfg:
                    raise ConfigConflictError("security.on_behalf_of is already configured differently "
                                              "in this process")
                return True
            CredentialBrokerFactory._store = SubjectTokenStore.from_config(cfg.get("token_store"))
            CredentialBrokerFactory._config = cfg
        log.info("[Factory] on_behalf_of enabled (broker=%s)", cfg.get("broker", "token_exchange"))
        return True

    @staticmethod
    def enabled() -> bool:
        return CredentialBrokerFactory._config is not None

    @staticmethod
    def token_store() -> Optional[SubjectTokenStore]:
        return CredentialBrokerFactory._store

    @staticmethod
    def broker() -> BaseCredentialBroker:
        """The configured broker, built on first use (it reads its client secret then)."""
        if CredentialBrokerFactory._config is None:
            raise CredentialUnavailableError(
                "a connector asks for on_behalf_of credentials but security.on_behalf_of is not "
                "enabled in this process")
        with CredentialBrokerFactory._lock:
            if CredentialBrokerFactory._broker is None:
                cfg = CredentialBrokerFactory._config
                cls = CredentialBrokerFactory._class_for(str(cfg.get("broker", "token_exchange")).lower())
                CredentialBrokerFactory._broker = cls.from_config(cfg, CredentialBrokerFactory._store)
            return CredentialBrokerFactory._broker

    @staticmethod
    def headers_for(audience: str, connector: Optional[str] = None) -> Dict[str, str]:
        """Per-call headers for ``audience``, acting for the current verified caller.
        Raises ``CredentialUnavailableError`` (a ``PermissionError``) when there is none."""
        caller = current_caller()
        agent = current_agent()
        if caller is None:
            raise CredentialUnavailableError(
                f"{connector or 'connector'} acts on behalf of the caller (audience {audience!r}) but this "
                "call has no verified caller (not inside an orchestrator flow admitted by BaseRouter.admit())")
        return CredentialBrokerFactory.broker().headers_for(audience, caller, agent=agent, connector=connector)

    @staticmethod
    def reset() -> None:
        with CredentialBrokerFactory._lock:
            CredentialBrokerFactory._config = None
            CredentialBrokerFactory._store = None
            CredentialBrokerFactory._broker = None
