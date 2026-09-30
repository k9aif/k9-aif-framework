# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import inspect
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance, require_governance

try:
    from k9_aif_abb.k9_security.zero_trust.context import (
        ExecutionContext,
        IdentityContext,
        AttributeContext,
        DestinationContext,
    )
    from k9_aif_abb.k9_security.zero_trust.guards import (
        DefaultZeroTrustGuard,
    )
    from k9_aif_abb.k9_security.zero_trust.enforcers import (
        RuntimePolicyEnforcer,
    )

    from k9_aif_abb.k9_security.zero_trust.identity import (
        CLAIM_FIELDS,
        CREDENTIALS_FIELD,
        SECRET_ENV,
        STAMP_FIELD,
        BaseIdentityResolver,
        build_authenticator,
        build_identity_resolver,
        sign_identity,
    )

    ZERO_TRUST_AVAILABLE = True
except ImportError:
    ZERO_TRUST_AVAILABLE = False


class BaseRouter(ABC):
    """
    BaseRouter
    ==========
    Abstract foundation for routing logic in the K9-AIF framework.

    Supports:
    - intent-based routing
    - governance pre/post hooks
    - optional Zero Trust execution enforcement
    - optional session management (K9SessionManager)
    """

    layer: str = "Router Base"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
        message_bus=None,
        governance=None,
        zero_trust_guard=None,
        policy_enforcer=None,
        enable_zero_trust: Optional[bool] = None,
        identity_resolver=None,
        authenticator=None,
        session_manager=None,
        object_store=None,
    ):
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        self.governance = require_governance(governance, self.config.get("k9_env"))
        self.registry: Dict[str, Any] = {}
        self._session_manager = session_manager or self._bootstrap_session(self.config)
        self.object_store = object_store or self._bootstrap_object_store(self.config)

        # Where Zero Trust gets caller identity from (None -> security.identity.mode,
        # default 'payload' in 1.x). See k9_security/zero_trust/identity.py.
        self.identity_resolver = identity_resolver
        # Verifies credentials in admit(); None -> security.auth.api_keys (if configured).
        self.authenticator = authenticator

        self.enable_zero_trust = (
            enable_zero_trust
            if enable_zero_trust is not None
            else self.config.get("enable_zero_trust", False)
        )

        if self.enable_zero_trust and ZERO_TRUST_AVAILABLE:
            self.zero_trust_guard = zero_trust_guard or DefaultZeroTrustGuard()
            self.policy_enforcer = policy_enforcer or RuntimePolicyEnforcer()
        else:
            self.zero_trust_guard = None
            self.policy_enforcer = None

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    def admit(
        self,
        payload: Dict[str, Any],
        credentials: Optional[Dict[str, Any]] = None,
        trust_zone: str = "internal",
        ttl_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """The trusted edge: authenticate the caller and stamp a signed identity.

        Call this where a request enters the system (an API handler, a
        consumer of an external topic) before route(). It

        1. authenticates ``credentials`` (or ``payload["_k9_credentials"]``)
           with the configured BaseAuthenticator;
        2. removes everything a caller could use to self-declare identity or
           trust (principal_id, principal_type, roles, tenant_id, trust_zone,
           any inbound stamp, the credentials themselves);
        3. adds an HMAC-signed identity stamp (``$K9_IDENTITY_SECRET``) that
           SignedIdentityResolver verifies in every Router/Orchestrator
           downstream, in this process or another.

        Failed or missing authentication returns the cleaned payload with no
        stamp: downstream it resolves as anonymous (high Zero Trust risk).
        """
        import os

        creds = credentials if credentials is not None else payload.get(CREDENTIALS_FIELD) or {}
        cleaned = {k: v for k, v in payload.items()
                   if k not in CLAIM_FIELDS and k not in (STAMP_FIELD, CREDENTIALS_FIELD)}
        if self.authenticator is None:
            self.authenticator = build_authenticator(self.config)
        identity = self.authenticator.authenticate(creds) if (self.authenticator and creds) else None
        if identity is None:
            self.logger.warning("[%s] admit: caller not authenticated; continuing as anonymous", self.layer)
            return cleaned
        secret = os.environ.get(SECRET_ENV, "")
        if not secret:
            raise ValueError(f"BaseRouter.admit() needs ${SECRET_ENV} to sign the identity")
        cleaned[STAMP_FIELD] = sign_identity(identity, secret, trust_zone=trust_zone, ttl_seconds=ttl_seconds)
        self.logger.info("[%s] admit: %s (%s) roles=%s", self.layer, identity.principal_id,
                         identity.principal_type, identity.roles)
        return cleaned

    def register_orchestrator(self, intent: str, orchestrator: Any):
        self.registry[intent] = orchestrator
        self.logger.info(f"[{self.layer}] Registered orchestrator for intent: {intent}")

    @abstractmethod
    def route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement route()")

    @staticmethod
    def _bootstrap_session(config: Dict[str, Any]):
        """Auto-create session manager from config when session.enabled: true. Returns None otherwise."""
        try:
            from k9_aif_abb.k9_factories.session_factory import SessionFactory
            return SessionFactory.create_manager(config)
        except Exception:
            return None

    @staticmethod
    def _bootstrap_object_store(config: Dict[str, Any]):
        """Auto-create object store from config.  Returns None when object_storage block is absent."""
        if not config.get("object_storage"):
            return None
        try:
            from k9_aif_abb.k9_factories.object_storage_factory import ObjectStorageFactory
            return ObjectStorageFactory.create(config)
        except Exception:
            return None

    def store_document(
        self,
        bucket: str,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a document in the object store and return its URI.

        Raises RuntimeError if no object_store is configured.
        """
        if self.object_store is None:
            raise RuntimeError(
                "No object_store configured — add an object_storage block to config.yaml"
            )
        return self.object_store.upload(bucket, key, data, metadata)

    def normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._enrich_with_session(payload)

    def _enrich_with_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attach session context to inbound payload.

        No-op when no session_manager is configured — existing behaviour preserved.
        Called automatically from normalize(). Subclasses that override normalize()
        without calling super() can call this explicitly.
        """
        if self._session_manager is None:
            return payload
        session_id = self._session_manager.extract_session_id(payload)
        if session_id:
            session = self._session_manager.on_session_get(session_id)
        else:
            user_id = payload.get("user_id", "anonymous")
            session = self._session_manager.on_session_start(user_id)
        return self._session_manager.enrich_payload(session, payload)

    def _update_session(self, session_id: str, context_delta: Dict[str, Any]) -> None:
        """Persist result context back to session. No-op when no session_manager."""
        if self._session_manager is not None and session_id:
            self._session_manager.on_session_update(session_id, context_delta)

    def apply_zero_trust(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Applies the K9 Zero Trust Execution Layer before routing.
        """

        if not self.enable_zero_trust:
            return {
                "allowed": True,
                "decision": "BYPASSED",
                "reason": "Zero Trust disabled",
                "risk_score": 0.0,
                "obligations": [],
                "payload": payload,
            }

        if not ZERO_TRUST_AVAILABLE:
            self.logger.warning(
                "[ZeroTrust] Enabled but zero trust package is unavailable. Bypassing."
            )
            return {
                "allowed": True,
                "decision": "UNAVAILABLE_BYPASS",
                "reason": "Zero Trust package unavailable",
                "risk_score": 0.0,
                "obligations": [],
                "payload": payload,
            }

        execution_context = self._zero_trust_context(payload, ctx)

        decision = self.zero_trust_guard.evaluate(execution_context)
        decision = self.policy_enforcer.enforce(execution_context, decision)

        self.logger.info(
            "[ZeroTrust][Router] decision=%s allowed=%s risk=%s reason=%s",
            decision.decision.value,
            decision.allowed,
            decision.risk_score,
            decision.reason,
        )

        return {
            "allowed": decision.allowed,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "risk_score": decision.risk_score,
            "obligations": decision.obligations,
            "payload": execution_context.payload,
        }

    def _resolve_identity(self, payload: Dict[str, Any], ctx: Optional[Dict[str, Any]], component_type: str):
        """Caller identity + trust zone, from the configured identity resolver
        (``identity_resolver=`` or ``security.identity.mode``). Built lazily so a
        signed-mode resolver only needs its secret where Zero Trust actually runs."""
        if self.identity_resolver is None:
            self.identity_resolver = build_identity_resolver(self.config)
        return self.identity_resolver.resolve(payload, ctx or {}, self.__class__.__name__, component_type)

    def _zero_trust_context(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ):
        ctx = ctx or {}
        resolved = self._resolve_identity(payload, ctx, "router")

        return ExecutionContext(
            request_id=payload.get("request_id")
            or ctx.get("request_id")
            or str(uuid.uuid4()),
            session_id=payload.get("session_id") or ctx.get("session_id"),
            workflow_id=payload.get("workflow_id") or ctx.get("workflow_id"),
            source_type=payload.get("source_type", "router"),
            action_type=payload.get("action_type", "route"),
            identity=resolved.identity,
            attributes=AttributeContext(
                data_sensitivity=payload.get("data_sensitivity", "low"),
                environment=payload.get(
                    "environment",
                    self.config.get("environment", "dev"),
                ),
                trust_zone=resolved.trust_zone,
                labels=payload.get("labels", {}),
            ),
            destination=DestinationContext(
                destination_type=payload.get("destination_type", "orchestrator"),
                destination_name=payload.get("destination_name", "routing_registry"),
                destination_uri=payload.get("destination_uri"),
                is_external=payload.get("is_external", False),
            ),
            payload=payload,
        )

    async def apply_pre_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self.governance.pre_process(payload, ctx or self._governance_context())
        if inspect.isawaitable(result):
            result = await result
        return result

    async def apply_post_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self.governance.post_process(payload, ctx or self._governance_context())
        if inspect.isawaitable(result):
            result = await result
        return result

    def _governance_context(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "component": self.__class__.__name__,
            "component_type": "router",
        }