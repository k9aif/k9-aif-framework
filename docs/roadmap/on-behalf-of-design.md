# Acting for the caller on outbound calls (1.36.0)

Status: built, opt-in (`security.on_behalf_of`). Not released.

## Problem

`BaseRouter.admit()` authenticated the caller and signed a stamp, but the identity stopped at the
orchestrator. MCP connectors sent one fixed `api_key`, so an AP clerk and an AP controller sending the
same request reached the MCP server with the same rights. The caller's own token was discarded at the
edge, so nothing downstream could exchange it.

## Decision: one exchange, at the last hop

| Hop | What happens |
|---|---|
| Login | The person signs in through the identity provider (Keycloak). Token `aud` = the K9-AIF application client. |
| Router | `admit()` validates the token (`OIDCAuthenticator`), keeps it server side, and signs a stamp with a random `token_ref`. |
| Orchestrator → squads → agents | In process: the verified caller travels as a context variable. No token exchange, no per-squad clients. |
| Connector (just before the MCP call) | One RFC 8693 token exchange: caller's token + the application's client credentials → token with `aud` = MCP server, `sub` = the person. |
| MCP server | Validates the token (signature, issuer, `aud` = itself, expiry) and decides from the person's roles. The authoritative check. |
| MCP server → backend | The server's own exchange; outside the framework. |

Why not the per-squad or per-agent exchange: squads and agents run in one process and share its memory, so
per-agent client secrets are not a security boundary there. Per-agent identity in the token becomes worth it
when agents run in their own containers (the agent handshake / gateway idea).

Why not forward the caller's token: its audience is the application, not the MCP server; a correct server
rejects it, and the MCP authorization spec forbids token passthrough.

Why the token stays out of the payload: payloads become Kafka events, kept for days and readable by every
consumer of the topic. Only the HMAC-signed `token_ref` travels.

## Who knows which agent acted

The token names the application (`azp`) and the person (`sub`). The framework records the agent: the
`BaseAgent` wrapper sets `ACTIVE_AGENT`; each exchange logs and emits an `OnBehalfOf` trace event with agent,
caller, audience and connector. Agent rights (the extraction agent never calls `release_payment`, even for a
controller) stay with the tool gate (`security.tool_gate`).

## Components

| Piece | Where |
|---|---|
| `CallerContext`, `ACTIVE_CALLER`, `ACTIVE_AGENT` | `k9_core/identity/caller_context.py` |
| `SubjectTokenStore` (any `BaseCache`) | `k9_core/identity/subject_token_store.py` |
| `BaseCredentialBroker` (ABB), `CredentialUnavailableError` | `k9_core/identity/base_credential_broker.py` |
| `TokenExchangeCredentialBroker` (OOB, RFC 8693) | `k9_security/credentials/token_exchange_broker.py` |
| `CredentialBrokerFactory` | `k9_factories/credential_broker_factory.py` |
| `token_ref` in the stamp | `k9_security/zero_trust/identity.py` (`sign_identity`, `verify_identity`) |
| Hook | `BaseConnector.on_behalf_of_headers()`; used by `MCPStreamableHttpConnector`, `MCPHttpConnector` |

## Configuration

```yaml
security:
  identity: {mode: signed}
  auth:
    providers:
      - type: keycloak
        issuer: ${KEYCLOAK_URL}/realms/k9x
        audience: k9-ap-app
  on_behalf_of:
    enabled: true
    broker: token_exchange
    token_endpoint: ${KEYCLOAK_URL}/realms/k9x/protocol/openid-connect/token
    client_id: k9-ap-app
    client_secret_env: K9_OBO_CLIENT_SECRET
    token_store: {provider: in_memory}    # redis when router and orchestrator are separate processes

# the connector
name: ap-mcp-client
kwargs:
  url: ${AP_MCP_URL}
  on_behalf_of: {audience: ap-mcp}
```

## Keycloak (26.2+, standard token exchange)

- Client `k9x-ap-login` (public, PKCE): where people sign in. A client scope with an audience mapper puts
  `k9-ap-app` in the login token's `aud` (required: the exchanging client must be in the subject token's audience).
- Client `k9-ap-app` (confidential): **Standard token exchange** on. Optional client scope with an audience
  mapper for `ap-mcp`, so it may request `audience=ap-mcp`.
- Client `ap-mcp`: owns client roles per tool (`invoice.read`, `po.match`, `dup.check`, `payment.release`);
  realm roles `ap_clerk` / `ap_controller` are composites of them.
- Access token lifespan a few minutes.

Verify by hand before wiring: exchange a clerk's and a controller's token with curl and compare
`resource_access.ap-mcp.roles`.

## Not yet

- `HttpApiAdapter` and `SqlDataAdapter` (role-mapped credentials via `BaseSecretManager` for backends without OAuth).
- The agent in the token (`act` claim or per-agent clients): when agents run in separate containers.
- HIL resume: a tool call resumed after review has no caller; a connector acting for the caller refuses it.
  Decide whom the resumed call acts for (the approver, or a service identity with the recorded decision),
  never the original person's stale token.
- Revocation between exchanges: bounded by token lifetimes (short access tokens; the exchanged-token cache
  expires 30 seconds before the token).
- Unattended batch (no person): a service-account client with only the intake roles.
