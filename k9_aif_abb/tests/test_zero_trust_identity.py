# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Authenticated caller identity for Zero Trust (1.14): an agent can no longer
grant itself roles or a trust zone by writing them into the payload -- when
the solution opts into signed identity. The 1.x default (payload) is unchanged."""

import pytest

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.router.base_router import BaseRouter
from k9_aif_abb.k9_security.zero_trust.context import IdentityContext
from k9_aif_abb.k9_security.zero_trust.guards import DefaultZeroTrustGuard, RoleBasedAuthorizationGuard
from k9_aif_abb.k9_security.zero_trust.identity import (
    STAMP_FIELD, ApiKeyAuthenticator, PayloadIdentityResolver, SignedIdentityResolver,
    build_identity_resolver, sign_identity, verify_identity)

SECRET = "test-secret-not-for-production"
CLAIMS_APPROVER = IdentityContext(principal_id="claims-bot", principal_type="agent", roles=["claims_approver"])


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("K9_IDENTITY_SECRET", SECRET)
    monkeypatch.setenv("K9_KEY_CLAIMS_BOT", "key-claims-bot")


def _guard():
    return DefaultZeroTrustGuard(authorization_guard=RoleBasedAuthorizationGuard(
        role_policy={"approve_claim": ["claims_approver"]}))


class ClaimsOrchestrator(BaseOrchestrator):
    layer = "ClaimsOrchestrator"

    def execute_flow(self, payload):
        return payload


class EdgeRouter(BaseRouter):
    layer = "EdgeRouter"

    def route(self, payload):
        return payload


def _orchestrator(mode):
    cfg = {"security": {"identity": {"mode": mode}}}
    return ClaimsOrchestrator(config=cfg, enable_zero_trust=True, zero_trust_guard=_guard())


def _router(**kw):
    cfg = {"security": {"auth": {"api_keys": {"claims-bot": {
        "env": "K9_KEY_CLAIMS_BOT", "principal_type": "agent", "roles": ["claims_approver"]}}}}}
    return EdgeRouter(config=cfg, **kw)


SPOOF = {"action_type": "approve_claim", "principal_id": "claims-bot", "principal_type": "agent",
         "roles": ["claims_approver"], "trust_zone": "internal", "claim_id": "CLM-1"}


# ── signing ───────────────────────────────────────────────────────────────────
def test_signed_stamp_round_trips_and_detects_tampering_and_expiry():
    stamp = sign_identity(CLAIMS_APPROVER, SECRET, now=1000, ttl_seconds=60)
    ok = verify_identity(stamp, SECRET, now=1030)
    assert ok.verified and ok.identity.roles == ["claims_approver"] and ok.identity.principal_type == "agent"
    assert verify_identity({**stamp, "roles": ["admin"]}, SECRET, now=1030) is None   # tampered
    assert verify_identity(stamp, SECRET, now=1100) is None                           # expired
    assert verify_identity(stamp, "other-secret", now=1030) is None                   # wrong key
    assert verify_identity({"principal_id": "x"}, SECRET) is None                     # unsigned


def test_api_key_authenticator_reads_keys_from_env_only():
    auth = ApiKeyAuthenticator({"claims-bot": {"env": "K9_KEY_CLAIMS_BOT", "principal_type": "agent",
                                               "roles": ["claims_approver"]}})
    who = auth.authenticate({"api_key": "key-claims-bot"})
    assert who.principal_id == "claims-bot" and who.principal_type == "agent"
    assert auth.authenticate({"api_key": "wrong"}) is None
    assert auth.authenticate({}) is None


# ── resolvers ─────────────────────────────────────────────────────────────────
def test_default_mode_is_payload_and_behaves_as_before():
    assert isinstance(build_identity_resolver({}), PayloadIdentityResolver)
    r = PayloadIdentityResolver().resolve({}, {}, "ClaimsOrchestrator", "orchestrator")
    assert r.identity.principal_id == "ClaimsOrchestrator" and r.trust_zone == "internal"
    assert not r.verified


def test_signed_mode_needs_a_secret(monkeypatch):
    monkeypatch.delenv("K9_IDENTITY_SECRET")
    with pytest.raises(ValueError, match="K9_IDENTITY_SECRET"):
        SignedIdentityResolver()
    with pytest.raises(ValueError):
        build_identity_resolver({"security": {"identity": {"mode": "sometimes"}}})


def test_signed_resolver_ignores_self_declared_identity():
    r = SignedIdentityResolver().resolve(SPOOF, {}, "ClaimsOrchestrator", "orchestrator")
    assert r.identity.principal_type == "anonymous" and r.identity.roles == [] and r.trust_zone == "untrusted"


def test_signed_resolver_prefers_trusted_context_then_valid_stamp():
    res = SignedIdentityResolver()
    via_ctx = res.resolve(SPOOF, {"identity": CLAIMS_APPROVER}, "C", "orchestrator")
    assert via_ctx.source == "context" and via_ctx.identity.roles == ["claims_approver"]
    stamped = {**SPOOF, "roles": ["admin"], STAMP_FIELD: sign_identity(CLAIMS_APPROVER, SECRET)}
    via_stamp = res.resolve(stamped, {}, "C", "orchestrator")
    assert via_stamp.source == "signed" and via_stamp.identity.roles == ["claims_approver"]   # not "admin"


# ── the attack, end to end ────────────────────────────────────────────────────
def test_payload_mode_is_still_spoofable_which_is_why_signed_exists():
    assert _orchestrator("payload").apply_zero_trust(SPOOF)["allowed"] is True


def test_signed_mode_denies_an_agent_that_grants_itself_a_role():
    zt = _orchestrator("signed").apply_zero_trust(SPOOF)
    assert zt["allowed"] is False and "anonymous" in zt["reason"]


def test_admitted_caller_is_authorized_downstream():
    router = _router()
    admitted = router.admit({"action_type": "approve_claim", "claim_id": "CLM-1",
                             "roles": ["admin"], "trust_zone": "internal"},
                            credentials={"api_key": "key-claims-bot"})
    assert "roles" not in admitted and "trust_zone" not in admitted and STAMP_FIELD in admitted
    zt = _orchestrator("signed").apply_zero_trust(admitted)
    assert zt["allowed"] is True


def test_admit_with_bad_credentials_strips_claims_and_stays_anonymous():
    admitted = _router().admit({**SPOOF, "_k9_credentials": {"api_key": "wrong"}})
    assert STAMP_FIELD not in admitted and "roles" not in admitted and "_k9_credentials" not in admitted
    assert _orchestrator("signed").apply_zero_trust(admitted)["allowed"] is False


def test_admit_drops_an_inbound_forged_stamp():
    forged = {**SPOOF, STAMP_FIELD: sign_identity(CLAIMS_APPROVER, "attacker-guess")}
    admitted = _router().admit(forged)                        # no credentials presented
    assert STAMP_FIELD not in admitted


def test_admit_refuses_to_run_without_a_signing_secret(monkeypatch):
    monkeypatch.delenv("K9_IDENTITY_SECRET")
    with pytest.raises(ValueError, match="K9_IDENTITY_SECRET"):
        _router().admit({"claim_id": "x"}, credentials={"api_key": "key-claims-bot"})


def test_router_zero_trust_uses_the_same_resolver():
    router = _router(enable_zero_trust=True, zero_trust_guard=_guard(),
                     identity_resolver=SignedIdentityResolver())
    assert router.apply_zero_trust(SPOOF)["allowed"] is False
    assert router.apply_zero_trust(router.admit(dict(SPOOF), {"api_key": "key-claims-bot"}))["allowed"] is True
