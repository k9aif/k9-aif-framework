# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""OIDCAuthenticator: OIDC bearer tokens (Keycloak shape) -> IdentityContext,
with locally generated keys (no network). The live Keycloak check is
examples/zero_trust_execution_demo/keycloak_demo.py."""

import time

import pytest

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

from k9_aif_abb.k9_security.zero_trust.identity import (  # noqa: E402
    ApiKeyAuthenticator, ChainedAuthenticator, build_authenticator)
from k9_aif_abb.k9_security.zero_trust.oidc_authenticator import OIDCAuthenticator  # noqa: E402

ISSUER = "http://keycloak.test:8113/realms/k9x"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=KEY, **overrides):
    now = int(time.time())
    claims = {"iss": ISSUER, "iat": now, "exp": now + 300, "sub": "u-1",
              "preferred_username": "k9x", "realm_access": {"roles": ["claims_approver", "offline_access"]}}
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


def _auth(**kw):
    return OIDCAuthenticator(issuer=ISSUER, key_resolver=lambda t: KEY.public_key(), **kw)


def test_valid_keycloak_token_becomes_an_identity():
    who = _auth().authenticate({"bearer_token": _token()})
    assert who.principal_id == "k9x" and who.principal_type == "user"
    assert "claims_approver" in who.roles


def test_authorization_header_form_is_accepted():
    assert _auth().authenticate({"authorization": "Bearer " + _token()}).principal_id == "k9x"


@pytest.mark.parametrize("token,why", [
    (lambda: _token(key=OTHER_KEY), "signed by someone else"),
    (lambda: _token(iss="http://evil.test/realms/k9x"), "wrong issuer"),
    (lambda: _token(exp=int(time.time()) - 600, iat=int(time.time()) - 900), "expired"),
    (lambda: _token()[:-4] + "AAAA", "tampered signature"),
    (lambda: "not-a-jwt", "garbage"),
])
def test_invalid_tokens_are_rejected_not_raised(token, why):
    assert _auth().authenticate({"bearer_token": token()}) is None, why


def test_audience_is_enforced_when_configured():
    auth = _auth(audience="k9x-agents")
    assert auth.authenticate({"bearer_token": _token(aud="account")}) is None
    assert auth.authenticate({"bearer_token": _token(aud="k9x-agents")}) is not None


def test_service_accounts_are_agents():
    who = _auth().authenticate({"bearer_token": _token(preferred_username="service-account-claims-bot")})
    assert who.principal_id == "claims-bot" and who.principal_type == "agent"


def test_custom_roles_and_tenant_claims():
    who = _auth(roles_claim="groups", tenant_claim="tenant").authenticate(
        {"bearer_token": _token(groups=["claims_reader"], tenant="acme")})
    assert who.roles == ["claims_reader"] and who.tenant_id == "acme"


def test_no_credentials_means_no_identity():
    assert _auth().authenticate({}) is None


def test_builder_chains_oidc_then_api_keys(monkeypatch):
    monkeypatch.setenv("K9_KEY_BOT", "k-1")
    auth = build_authenticator({"security": {"auth": {
        "oidc": {"issuer": ISSUER},
        "api_keys": {"bot": {"env": "K9_KEY_BOT", "principal_type": "agent", "roles": ["r"]}}}}})
    assert isinstance(auth, ChainedAuthenticator)
    assert isinstance(auth.authenticators[0], OIDCAuthenticator)
    assert isinstance(auth.authenticators[1], ApiKeyAuthenticator)
    assert auth.authenticate({"api_key": "k-1"}).principal_id == "bot"
