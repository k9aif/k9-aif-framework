# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""AuthenticatorFactory + IdP adapters (Keycloak, Entra ID, Okta) + OIDC discovery.
Locally generated keys, no network (the live Keycloak run is keycloak_demo.py)."""

import json
import time

import pytest

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

from k9_aif_abb.k9_factories.authenticator_factory import AuthenticatorFactory  # noqa: E402
from k9_aif_abb.k9_security.zero_trust.context import IdentityContext  # noqa: E402
from k9_aif_abb.k9_security.zero_trust.identity import (  # noqa: E402
    ApiKeyAuthenticator, BaseAuthenticator, ChainedAuthenticator, build_authenticator)
from k9_aif_abb.k9_security.zero_trust.idp_adapters import (  # noqa: E402
    EntraIDAuthenticator, KeycloakAuthenticator, OktaAuthenticator)
from k9_aif_abb.k9_security.zero_trust.oidc_authenticator import OIDCAuthenticator  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(iss, **claims):
    now = int(time.time())
    return jwt.encode({"iss": iss, "iat": now, "exp": now + 300, **claims}, KEY, algorithm="RS256")


def _pin(auth):
    auth._key_resolver = lambda t: KEY.public_key()
    return auth


# ── factory ──────────────────────────────────────────────────────────────────
def test_oob_authenticators_are_registered():
    assert {"api_key", "oidc", "keycloak", "entra_id", "okta"} <= set(AuthenticatorFactory.available())


def test_factory_is_static():
    with pytest.raises(RuntimeError):
        AuthenticatorFactory()


def test_providers_list_builds_in_order_and_chains(monkeypatch):
    monkeypatch.setenv("K9_KEY_BOT", "k-1")
    auth = AuthenticatorFactory.create({"security": {"auth": {"providers": [
        {"type": "keycloak", "base_url": "http://kc:8113", "realm": "k9x", "client_id": "k9x-agents"},
        {"type": "api_key", "api_keys": {"bot": {"env": "K9_KEY_BOT", "roles": ["r"]}}},
    ]}}})
    assert isinstance(auth, ChainedAuthenticator)
    kc, keys = auth.authenticators
    assert isinstance(kc, KeycloakAuthenticator) and kc.issuer == "http://kc:8113/realms/k9x"
    assert isinstance(keys, ApiKeyAuthenticator)
    assert auth.authenticate({"api_key": "k-1"}).principal_id == "bot"


def test_single_provider_is_returned_directly_and_nothing_means_none():
    auth = AuthenticatorFactory.create({"security": {"auth": {"providers": [
        {"type": "oidc", "issuer": "https://idp.example/realms/x"}]}}})
    assert type(auth) is OIDCAuthenticator
    assert AuthenticatorFactory.create({}) is None


def test_earlier_config_shape_still_works(monkeypatch):
    monkeypatch.setenv("K9_KEY_BOT", "k-1")
    auth = build_authenticator({"security": {"auth": {
        "oidc": {"issuer": "https://idp.example/realms/x"},
        "api_keys": {"bot": {"env": "K9_KEY_BOT"}}}}})
    assert [type(a) for a in auth.authenticators] == [OIDCAuthenticator, ApiKeyAuthenticator]


def test_solution_sbbs_can_register_their_own():
    class CACAuthenticator(BaseAuthenticator):
        def __init__(self, allowed):
            self.allowed = allowed

        @classmethod
        def from_config(cls, cfg):
            return cls(cfg["allowed"])

        def authenticate(self, credentials):
            dn = credentials.get("client_cert_dn")
            return IdentityContext(principal_id=dn, principal_type="user", roles=["analyst"]) \
                if dn in self.allowed else None

    AuthenticatorFactory.register("cac", CACAuthenticator)
    auth = AuthenticatorFactory.create({"security": {"auth": {"providers": [
        {"type": "cac", "allowed": ["CN=DOE.JANE.1234567890"]}]}}})
    assert auth.authenticate({"client_cert_dn": "CN=DOE.JANE.1234567890"}).roles == ["analyst"]
    assert auth.authenticate({"client_cert_dn": "CN=MALLORY"}) is None


def test_unknown_type_is_a_clear_error():
    with pytest.raises(ValueError, match="Unknown authenticator type"):
        AuthenticatorFactory.create({"security": {"auth": {"providers": [{"type": "nope"}]}}})


# ── Keycloak ─────────────────────────────────────────────────────────────────
KC_ISS = "http://kc:8113/realms/k9x"


def test_keycloak_reads_realm_and_own_client_roles_only():
    auth = _pin(KeycloakAuthenticator(base_url="http://kc:8113", realm="k9x", client_id="k9x-agents"))
    who = auth.authenticate({"bearer_token": _token(
        KC_ISS, preferred_username="k9aif",
        realm_access={"roles": ["claims_reader"]},
        resource_access={"k9x-agents": {"roles": ["claims_auditor"]},
                         "some-other-app": {"roles": ["admin"]}})})
    assert who.roles == ["claims_reader", "claims_auditor"]          # never the other client's "admin"
    assert who.principal_type == "user"


def test_keycloak_service_account_is_an_agent_and_issuer_is_enforced():
    auth = _pin(KeycloakAuthenticator(issuer=KC_ISS))
    who = auth.authenticate({"bearer_token": _token(KC_ISS, preferred_username="service-account-claims-bot")})
    assert who.principal_id == "claims-bot" and who.principal_type == "agent"
    assert auth.authenticate({"bearer_token": _token("http://evil/realms/k9x", preferred_username="x")}) is None


def test_keycloak_needs_issuer_or_base_url_and_realm():
    with pytest.raises(ValueError):
        KeycloakAuthenticator(base_url="http://kc:8113")


# ── Entra ID ─────────────────────────────────────────────────────────────────
def test_entra_id_app_roles_and_app_only_tokens():
    auth = _pin(EntraIDAuthenticator(tenant_id="t-1", audience="api://k9x"))
    assert auth.issuer == "https://login.microsoftonline.com/t-1/v2.0"
    iss = auth.issuer
    user = auth.authenticate({"bearer_token": _token(iss, aud="api://k9x", preferred_username="jane@agency.gov",
                                                     roles=["Claims.Approve"], tid="t-1")})
    assert user.principal_id == "jane@agency.gov" and user.roles == ["Claims.Approve"] and user.tenant_id == "t-1"
    app = auth.authenticate({"bearer_token": _token(iss, aud="api://k9x", idtyp="app", azp="claims-bot-app")})
    assert app.principal_type == "agent" and app.principal_id == "claims-bot-app"
    assert auth.authenticate({"bearer_token": _token(iss, aud="api://other", preferred_username="x")}) is None


# ── Okta ─────────────────────────────────────────────────────────────────────
def test_okta_groups_and_client_credentials():
    auth = _pin(OktaAuthenticator(domain="agency.okta.com"))
    iss = "https://agency.okta.com/oauth2/default"
    assert auth.issuer == iss and auth.jwks_uri == iss + "/v1/keys"
    user = auth.authenticate({"bearer_token": _token(iss, aud="api://default", sub="jane@agency.gov",
                                                     groups=["claims_reader"])})
    assert user.roles == ["claims_reader"] and user.principal_type == "user"
    bot = auth.authenticate({"bearer_token": _token(iss, aud="api://default", sub="0oa1bot", cid="0oa1bot")})
    assert bot.principal_type == "agent"


# ── OIDC discovery ───────────────────────────────────────────────────────────
class _Doc:
    def __init__(self, doc):
        self._b = json.dumps(doc).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_discovery_reads_jwks_uri_and_refuses_a_mismatched_issuer(monkeypatch):
    import urllib.request
    iss = "https://idp.example/tenant"
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10: _Doc({"issuer": iss, "jwks_uri": iss + "/keys"}))
    auth = OIDCAuthenticator(issuer=iss, discovery=True)
    assert auth.jwks_uri == "" and auth._discover_jwks_uri() == iss + "/keys"
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10: _Doc({"issuer": "https://evil.example", "jwks_uri": "x"}))
    with pytest.raises(ValueError, match="does not match"):
        auth._discover_jwks_uri()
