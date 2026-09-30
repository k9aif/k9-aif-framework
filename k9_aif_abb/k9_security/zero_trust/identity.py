# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Caller identity for Zero Trust: who is calling, and how do we know.

Zero Trust authorizes by identity (``IdentityContext.roles``) and trust zone.
Until 1.14 both base classes read those straight from the payload
(``payload["principal_id"|"roles"|"trust_zone"]``): a caller -- including
another agent -- could simply claim ``roles: ["admin"]``. Zscaler ThreatLabz's
2026 report predicts exactly this ("spoofed interactions between systems";
"security must extend to non-human identities, enforcing authentication").

Two ABB contracts, three OOB SBBs:

    BaseAuthenticator            verifies credentials at the edge -> IdentityContext
      ApiKeyAuthenticator          API key -> principal (agent / service / user), roles, tenant
      OIDCAuthenticator            OIDC bearer token (Keycloak, Entra ID, Okta, ...) -> identity
                                   (oidc_authenticator.py; pip install "k9-aif[oidc]")
    BaseIdentityResolver         where BaseRouter/BaseOrchestrator get identity from
      PayloadIdentityResolver      legacy: self-declared payload fields (the 1.x default; warns)
      SignedIdentityResolver       only an HMAC-signed stamp or a trusted in-process ctx

The signed stamp exists because routers and orchestrators often run in
separate processes (the EOC talks over Kafka): a plain identity field could
be written by anything in between. The trusted edge -- ``BaseRouter.admit()``
-- authenticates, strips whatever identity the caller claimed, and stamps a
signed one; every component downstream verifies it with the shared secret
(``K9_IDENTITY_SECRET``). Unsigned or tampered -> anonymous, which Zero
Trust's risk evaluator already scores as high risk.

Select with config (``security.identity.mode: payload | signed``) or pass
``identity_resolver=`` to a Router/Orchestrator. 1.x default: payload (with a
warning), so existing solutions behave exactly as before.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .context import IdentityContext

log = logging.getLogger("governance.zero_trust.identity")

STAMP_FIELD = "_k9_identity"
CREDENTIALS_FIELD = "_k9_credentials"
# Fields a caller could use to self-declare identity or trust. SignedIdentityResolver
# ignores them; BaseRouter.admit() removes them before stamping.
CLAIM_FIELDS = ("principal_id", "principal_type", "roles", "tenant_id", "trust_zone")
SECRET_ENV = "K9_IDENTITY_SECRET"


@dataclass
class ResolvedIdentity:
    identity: IdentityContext
    trust_zone: str
    verified: bool          # True only when the identity was authenticated/signed
    source: str             # "payload" | "signed" | "context" | "anonymous"


# ── authentication at the edge ────────────────────────────────────────────────
class BaseAuthenticator(ABC):
    """ABB: turn presented credentials into a verified identity, or None."""

    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any]) -> Optional[IdentityContext]:
        raise NotImplementedError


class ApiKeyAuthenticator(BaseAuthenticator):
    """OOB SBB: one API key per principal, keys read from the environment
    (never from config.yaml). Covers non-human identities: an agent or a
    service gets its own key, type and roles, exactly like a user.

    config (``security.auth.api_keys``)::

        claims-bot:
          env: K9_KEY_CLAIMS_BOT      # the key itself lives in .env
          principal_type: agent
          roles: [claims_reader]
          tenant_id: acme
    """

    def __init__(self, principals: Optional[Dict[str, Dict[str, Any]]] = None,
                 environ: Optional[Dict[str, str]] = None) -> None:
        env = os.environ if environ is None else environ
        self._by_key: Dict[str, IdentityContext] = {}
        for principal_id, spec in (principals or {}).items():
            key = env.get(spec.get("env", ""), "")
            if not key:
                log.warning("[ApiKeyAuthenticator] no key in $%s for principal '%s'; it cannot sign in",
                            spec.get("env"), principal_id)
                continue
            self._by_key[key] = IdentityContext(
                principal_id=principal_id,
                principal_type=spec.get("principal_type", "service"),
                roles=list(spec.get("roles", [])),
                tenant_id=spec.get("tenant_id"),
            )

    def authenticate(self, credentials: Dict[str, Any]) -> Optional[IdentityContext]:
        presented = str((credentials or {}).get("api_key", ""))
        if not presented:
            return None
        for key, identity in self._by_key.items():
            if hmac.compare_digest(key, presented):
                return identity
        return None


# ── signed identity stamp ────────────────────────────────────────────────────
def _canonical(fields: Dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_identity(identity: IdentityContext, secret: str, trust_zone: str = "internal",
                  ttl_seconds: int = 3600, now: Optional[float] = None) -> Dict[str, Any]:
    if not secret:
        raise ValueError("sign_identity needs a secret (K9_IDENTITY_SECRET)")
    issued = int(now if now is not None else time.time())
    fields = {
        "principal_id": identity.principal_id,
        "principal_type": identity.principal_type,
        "roles": sorted(identity.roles),
        "tenant_id": identity.tenant_id,
        "trust_zone": trust_zone,
        "iat": issued,
        "exp": issued + int(ttl_seconds),
    }
    sig = hmac.new(secret.encode("utf-8"), _canonical(fields), hashlib.sha256).hexdigest()
    return {**fields, "sig": sig}


def verify_identity(stamp: Any, secret: str, now: Optional[float] = None) -> Optional[ResolvedIdentity]:
    """The identity in a stamp, or None if unsigned, tampered or expired."""
    if not isinstance(stamp, dict) or not secret or "sig" not in stamp:
        return None
    fields = {k: v for k, v in stamp.items() if k != "sig"}
    expected = hmac.new(secret.encode("utf-8"), _canonical(fields), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(stamp["sig"])):
        return None
    if int(fields.get("exp", 0)) < int(now if now is not None else time.time()):
        return None
    return ResolvedIdentity(
        identity=IdentityContext(principal_id=fields["principal_id"],
                                 principal_type=fields["principal_type"],
                                 roles=list(fields.get("roles", [])),
                                 tenant_id=fields.get("tenant_id")),
        trust_zone=fields.get("trust_zone", "internal"),
        verified=True,
        source="signed",
    )


# ── where Zero Trust gets identity from ──────────────────────────────────────
class BaseIdentityResolver(ABC):
    """ABB: decide the caller's identity and trust zone for one request.

    ``component`` is the resolving Router/Orchestrator's name and
    ``component_type`` its kind ("router" | "orchestrator"), used as the
    legacy default principal."""

    @abstractmethod
    def resolve(self, payload: Dict[str, Any], ctx: Dict[str, Any],
                component: str, component_type: str) -> ResolvedIdentity:
        raise NotImplementedError


class PayloadIdentityResolver(BaseIdentityResolver):
    """OOB SBB (legacy, the 1.x default): identity is whatever the payload
    declares. Exactly the pre-1.14 behaviour, plus a one-time warning,
    because a caller can claim any role or trust zone this way."""

    _warned = False

    def resolve(self, payload, ctx, component, component_type):
        if not PayloadIdentityResolver._warned:
            PayloadIdentityResolver._warned = True
            log.warning("[ZeroTrust] identity is self-declared in the payload (security.identity.mode="
                        "payload). Any caller can claim roles or trust_zone. Use mode 'signed' with "
                        "BaseRouter.admit() for authenticated identity.")
        return ResolvedIdentity(
            identity=IdentityContext(
                principal_id=payload.get("principal_id", component),
                principal_type=payload.get("principal_type", component_type),
                roles=payload.get("roles", []),
                tenant_id=payload.get("tenant_id"),
            ),
            trust_zone=payload.get("trust_zone", "internal"),
            verified=False,
            source="payload",
        )


class SignedIdentityResolver(BaseIdentityResolver):
    """OOB SBB: identity only from (1) a trusted in-process ``ctx["identity"]``
    set by the calling code, or (2) a valid signed stamp in the payload.
    Self-declared payload fields are ignored (and reported); anything else
    is anonymous. Construction fails without a secret: a "secure" resolver
    that can't verify anything must not quietly act like the insecure one."""

    def __init__(self, secret: Optional[str] = None) -> None:
        self._secret = secret or os.environ.get(SECRET_ENV, "")
        if not self._secret:
            raise ValueError(f"SignedIdentityResolver needs a secret: set ${SECRET_ENV} "
                             "(the same value on every Router and Orchestrator process)")

    def resolve(self, payload, ctx, component, component_type):
        trusted = (ctx or {}).get("identity")
        if isinstance(trusted, IdentityContext):
            return ResolvedIdentity(trusted, (ctx or {}).get("trust_zone", "internal"), True, "context")
        verified = verify_identity(payload.get(STAMP_FIELD), self._secret)
        claimed = [f for f in CLAIM_FIELDS if f in payload]
        if claimed:
            _report_ignored_claims(component, claimed, bool(verified))
        if verified:
            return verified
        return ResolvedIdentity(
            identity=IdentityContext(principal_id="anonymous", principal_type="anonymous", roles=[]),
            trust_zone="untrusted",
            verified=False,
            source="anonymous",
        )


def _report_ignored_claims(component: str, claimed: List[str], had_stamp: bool) -> None:
    log.warning("[ZeroTrust] %s ignored self-declared identity fields %s (%s)", component, claimed,
                "signed identity used instead" if had_stamp else "no valid signed identity: anonymous")
    try:
        from k9_aif_abb.k9_utils.trace_events import emit_trace_event
        emit_trace_event({"type": "ZeroTrust", "agent": component, "decision": "IDENTITY_CLAIM_IGNORED",
                          "allowed": True, "risk": 0.0, "reason": f"ignored self-declared {claimed}"})
    except Exception:  # tracing is best-effort, never a reason to fail a request
        pass


def build_identity_resolver(config: Optional[Dict[str, Any]]) -> BaseIdentityResolver:
    """``security.identity.mode``: "payload" (default in 1.x) or "signed"."""
    mode = str(((config or {}).get("security", {}) or {}).get("identity", {}).get("mode", "payload")).lower()
    if mode == "signed":
        return SignedIdentityResolver()
    if mode != "payload":
        raise ValueError(f"security.identity.mode must be 'payload' or 'signed', not {mode!r}")
    return PayloadIdentityResolver()


class ChainedAuthenticator(BaseAuthenticator):
    """Tries each authenticator in order; the first identity wins."""

    def __init__(self, *authenticators: BaseAuthenticator) -> None:
        self.authenticators = [a for a in authenticators if a is not None]

    def authenticate(self, credentials: Dict[str, Any]) -> Optional[IdentityContext]:
        for auth in self.authenticators:
            identity = auth.authenticate(credentials)
            if identity is not None:
                return identity
        return None


def build_authenticator(config: Optional[Dict[str, Any]]) -> Optional[BaseAuthenticator]:
    """From ``security.auth``: ``oidc`` (bearer tokens from Keycloak / any OIDC
    provider; needs k9-aif[oidc]) and/or ``api_keys``. Both -> tried in that
    order. Neither -> None."""
    auth_cfg = (((config or {}).get("security", {}) or {}).get("auth", {}) or {})
    found: List[BaseAuthenticator] = []
    if auth_cfg.get("oidc"):
        from .oidc_authenticator import OIDCAuthenticator
        found.append(OIDCAuthenticator.from_config(auth_cfg["oidc"]))
    if auth_cfg.get("api_keys"):
        found.append(ApiKeyAuthenticator(auth_cfg["api_keys"]))
    if not found:
        return None
    return found[0] if len(found) == 1 else ChainedAuthenticator(*found)
