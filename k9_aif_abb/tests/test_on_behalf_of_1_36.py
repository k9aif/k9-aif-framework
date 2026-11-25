# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Acting for the caller on outbound calls (1.36.0, security.on_behalf_of).

Property: a connector configured with ``on_behalf_of`` reaches its server only with
a token addressed to that server that names the verified caller; two people sending
the same request reach the server as themselves; with no verified caller the call
does not run (never a shared key); the caller's own token never travels in a payload.
Which agent made the call is recorded by the framework (one client for the application).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent, _resolve_sync
from k9_aif_abb.k9_core.identity.base_credential_broker import (
    BaseCredentialBroker,
    CredentialUnavailableError,
)
from k9_aif_abb.k9_core.identity.caller_context import CallerContext, caller_scope
from k9_aif_abb.k9_core.identity.subject_token_store import SubjectTokenStore
from k9_aif_abb.k9_core.integration import mcp_http_connector
from k9_aif_abb.k9_core.integration.base_connector import BaseConnector
from k9_aif_abb.k9_core.integration.mcp_http_connector import MCPHttpConnector
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.router.base_router import BaseRouter
from k9_aif_abb.k9_factories.cache_factory import CacheFactory
from k9_aif_abb.k9_factories.credential_broker_factory import CredentialBrokerFactory
from k9_aif_abb.k9_factories.factory_errors import ConfigConflictError
from k9_aif_abb.k9_security.credentials.token_exchange_broker import (
    GRANT_TYPE,
    TokenExchangeCredentialBroker,
)
from k9_aif_abb.k9_security.zero_trust.context import IdentityContext
from k9_aif_abb.k9_security.zero_trust.identity import (
    STAMP_FIELD,
    BaseAuthenticator,
    sign_identity,
    verify_identity,
)
from k9_aif_abb.k9_squad.base_squad import BaseSquad

SECRET = "test-identity-secret"


# ── fixtures ────────────────────────────────────────────────────────────────
class PassGovernance:
    def pre_process(self, payload, ctx=None):
        return payload

    def post_process(self, payload, ctx=None):
        return payload


class StubBroker(BaseCredentialBroker):
    """Records what it was asked for; the token names the caller and audience."""
    calls: List[Dict[str, Any]] = []

    def __init__(self, token_store):
        self.token_store = token_store

    @classmethod
    def from_config(cls, cfg, token_store):
        return cls(token_store)

    def headers_for(self, audience, caller, *, agent=None, connector=None):
        StubBroker.calls.append({"audience": audience, "principal": caller.principal_id, "agent": agent,
                                 "connector": connector,
                                 "subject_token": self.token_store.get(caller.subject_token_ref)})
        return {"Authorization": f"Bearer for-{caller.principal_id}-at-{audience}"}


class KeyedAuthenticator(BaseAuthenticator):
    """Bearer token 'tok-<user>' authenticates <user>; roles by user."""
    ROLES = {"john": ["ap_clerk"], "jane": ["ap_controller"]}

    def authenticate(self, credentials):
        token = credentials.get("bearer_token", "")
        user = token[len("tok-"):] if token.startswith("tok-") else ""
        if user not in self.ROLES:
            return None
        return IdentityContext(principal_id=user, principal_type="user", roles=self.ROLES[user])


class RecordingConnector(BaseConnector):
    """Records the headers it would send; it never opens a connection."""
    sent: List[Dict[str, str]] = []

    def __init__(self, config):
        super().__init__(config, name=config.get("name"))

    async def call_tool(self, tool_name, arguments=None):
        headers = self.on_behalf_of_headers()
        RecordingConnector.sent.append(headers)
        return {"tool": tool_name, "ok": True}


class ExtractionAgent(BaseAgent):
    layer = "ExtractionAgent"

    def __init__(self, config, connector):
        super().__init__(config, governance=PassGovernance())
        self.connector = connector

    def execute(self, payload):
        return {"output": _resolve_sync(self.connector.call_tool("po_match", {"invoice": "123"}))}


class APRouter(BaseRouter):
    def route(self, payload):
        return payload


class APOrchestrator(BaseOrchestrator):
    layer = "APOrchestrator"

    def execute_flow(self, payload):
        return {}


def obo_config(**block) -> Dict[str, Any]:
    cfg = {"enabled": True, "broker": "stub", "token_store": {"provider": "in_memory"}}
    cfg.update(block)
    return {"k9_env": "test", "security": {"identity": {"mode": "signed"}, "on_behalf_of": cfg}}


def squad_with(agent) -> BaseSquad:
    squad = BaseSquad(squad_id="ap_squad", agents=[agent])
    squad.flow = [{"agent": type(agent).__name__, "result_key": "extraction"}]
    return squad


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("K9_IDENTITY_SECRET", SECRET)
    CredentialBrokerFactory.register("stub", StubBroker)
    StubBroker.calls = []
    RecordingConnector.sent = []
    yield
    CredentialBrokerFactory.reset()


def admitted(config, user) -> Dict[str, Any]:
    router = APRouter(config=config, governance=PassGovernance())
    router.authenticator = KeyedAuthenticator()
    return router.admit({"event_type": "invoice.received", "invoice": "123"},
                        credentials={"bearer_token": f"tok-{user}"})


# ── the stamp ───────────────────────────────────────────────────────────────
def test_stamp_carries_token_reference_and_older_stamps_still_verify():
    ident = IdentityContext(principal_id="john", principal_type="user", roles=["ap_clerk"])
    with_ref = verify_identity(sign_identity(ident, SECRET, token_ref="ref-1"), SECRET)
    without = verify_identity(sign_identity(ident, SECRET), SECRET)
    assert with_ref.token_ref == "ref-1"
    assert without is not None and without.token_ref is None
    tampered = sign_identity(ident, SECRET, token_ref="ref-1")
    tampered["token_ref"] = "someone-elses-ref"
    assert verify_identity(tampered, SECRET) is None


def test_admit_keeps_the_token_server_side_only():
    config = obo_config()
    payload = admitted(config, "john")
    assert "tok-john" not in json.dumps(payload)            # never in the payload / a Kafka event
    ref = payload[STAMP_FIELD]["token_ref"]
    assert CredentialBrokerFactory.token_store().get(ref) == "tok-john"


def test_admit_without_on_behalf_of_is_unchanged():
    payload = admitted({"k9_env": "test", "security": {"identity": {"mode": "signed"}}}, "john")
    assert "token_ref" not in payload[STAMP_FIELD]
    assert not CredentialBrokerFactory.enabled()


def test_on_behalf_of_requires_signed_identity():
    config = obo_config()
    config["security"]["identity"]["mode"] = "payload"
    with pytest.raises(ValueError, match="signed"):
        APOrchestrator(config=config, governance=PassGovernance())


def test_a_different_configuration_in_the_same_process_is_refused():
    APOrchestrator(config=obo_config(), governance=PassGovernance())
    with pytest.raises(ConfigConflictError):
        APOrchestrator(config=obo_config(token_store={"provider": "redis"}), governance=PassGovernance())


# ── the flow: router -> orchestrator -> squad -> agent -> connector ─────────
def run_flow(config, payload, connector_config):
    orch = APOrchestrator(config=config, governance=PassGovernance())
    agent = ExtractionAgent(config, RecordingConnector(connector_config))
    return orch.execute_squads([squad_with(agent)], payload)


def test_same_request_reaches_the_server_as_each_person():
    config = obo_config()
    conn_cfg = {"name": "ap-mcp-client", "kwargs": {"on_behalf_of": {"audience": "ap-mcp"}}}
    run_flow(config, admitted(config, "john"), conn_cfg)
    run_flow(config, admitted(config, "jane"), conn_cfg)
    assert RecordingConnector.sent == [{"Authorization": "Bearer for-john-at-ap-mcp"},
                                       {"Authorization": "Bearer for-jane-at-ap-mcp"}]
    # the framework knows which agent acted, for whom, with the caller's own token
    assert [(c["agent"], c["principal"], c["subject_token"], c["connector"]) for c in StubBroker.calls] == [
        ("ExtractionAgent", "john", "tok-john", "ap-mcp-client"),
        ("ExtractionAgent", "jane", "tok-jane", "ap-mcp-client"),
    ]


def test_parallel_squads_keep_the_caller():
    config = obo_config()
    conn_cfg = {"name": "c", "on_behalf_of": {"audience": "ap-mcp"}}
    orch = APOrchestrator(config=config, governance=PassGovernance())
    a = squad_with(ExtractionAgent(config, RecordingConnector(conn_cfg)))
    b = BaseSquad(squad_id="second", agents=[ExtractionAgent(config, RecordingConnector(conn_cfg))])
    b.flow = [{"agent": "ExtractionAgent", "result_key": "x"}]
    orch.execute_squads([a, b], admitted(config, "john"), parallel=True)
    assert RecordingConnector.sent == [{"Authorization": "Bearer for-john-at-ap-mcp"}] * 2


def test_no_verified_caller_means_the_call_does_not_run():
    config = obo_config()
    conn_cfg = {"name": "c", "kwargs": {"on_behalf_of": {"audience": "ap-mcp"}}}
    forged = {"event_type": "invoice.received", "principal_id": "jane", "roles": ["ap_controller"]}
    with pytest.raises(CredentialUnavailableError):
        run_flow(config, forged, conn_cfg)
    assert RecordingConnector.sent == [] and StubBroker.calls == []


def test_connector_without_on_behalf_of_is_unchanged():
    config = obo_config()
    run_flow(config, admitted(config, "john"), {"name": "plain"})
    assert RecordingConnector.sent == [{}]
    assert StubBroker.calls == []


def test_connector_asking_for_it_in_a_process_without_it_is_refused():
    config = {"k9_env": "test"}
    with caller_scope(CallerContext(principal_id="john", principal_type="user", subject_token_ref="r")):
        with pytest.raises(CredentialUnavailableError, match="not enabled"):
            RecordingConnector({"on_behalf_of": {"audience": "ap-mcp"}}).on_behalf_of_headers()
    assert config  # the process never configured on_behalf_of


def test_mcp_http_connector_sends_the_exchanged_token_instead_of_api_key(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(mcp_http_connector.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    config = obo_config()
    conn_cfg = {"name": "ap", "kwargs": {"base_url": "http://mcp.test", "api_key": "shared-key",
                                         "on_behalf_of": {"audience": "ap-mcp"}}}
    orch = APOrchestrator(config=config, governance=PassGovernance())
    agent = ExtractionAgent(config, MCPHttpConnector(conn_cfg))
    orch.execute_squads([squad_with(agent)], admitted(config, "john"))
    assert seen == ["Bearer for-john-at-ap-mcp"]


# ── the OOB token exchange broker (RFC 8693) ───────────────────────────────
def exchange_broker(responses):
    store = SubjectTokenStore(CacheFactory.get("in_memory"))
    posts = []

    def post(url, form, timeout):
        posts.append((url, form))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    broker = TokenExchangeCredentialBroker("https://idp.test/token", "k9-ap-app", "app-secret", store, post=post)
    ref = store.put("tok-john", 300)
    caller = CallerContext(principal_id="john", principal_type="user", subject_token_ref=ref)
    return broker, caller, posts


def test_exchange_sends_rfc_8693_form_and_caches_until_expiry():
    broker, caller, posts = exchange_broker([(200, {"access_token": "aud-ap-mcp", "expires_in": 300})])
    assert broker.headers_for("ap-mcp", caller, agent="ExtractionAgent") == {"Authorization": "Bearer aud-ap-mcp"}
    assert broker.headers_for("ap-mcp", caller, agent="ExtractionAgent") == {"Authorization": "Bearer aud-ap-mcp"}
    assert len(posts) == 1                                  # second call served from cache
    url, form = posts[0]
    assert url == "https://idp.test/token"
    assert form["grant_type"] == GRANT_TYPE
    assert form["subject_token"] == "tok-john" and form["audience"] == "ap-mcp"
    assert form["client_id"] == "k9-ap-app"


@pytest.mark.parametrize("response", [
    (403, {"error": "access_denied", "error_description": "client not allowed to exchange"}),
    (200, {}),
    ConnectionError("connection refused"),
])
def test_refused_or_unreachable_exchange_fails_closed(response):
    broker, caller, _ = exchange_broker([response])
    with pytest.raises(CredentialUnavailableError):
        broker.headers_for("ap-mcp", caller)


def test_caller_without_a_token_cannot_be_acted_for():
    broker, _, posts = exchange_broker([])
    api_key_caller = CallerContext(principal_id="batch", principal_type="agent", subject_token_ref=None)
    with pytest.raises(CredentialUnavailableError, match="no token"):
        broker.headers_for("ap-mcp", api_key_caller)
    assert posts == []


def test_broker_from_config_needs_the_client_secret(monkeypatch):
    monkeypatch.delenv("K9_OBO_CLIENT_SECRET", raising=False)
    store = SubjectTokenStore(CacheFactory.get("in_memory"))
    with pytest.raises(ValueError, match="client secret"):
        TokenExchangeCredentialBroker.from_config({"token_endpoint": "https://idp.test/token",
                                                   "client_id": "k9-ap-app"}, store)
