# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Acting for the caller (1.36.0, opt-in: ``security.on_behalf_of.enabled``).

The router authenticates the person (``BaseRouter.admit()``). This package
carries that person to the point where a call leaves the process, so a
connector can present a token that names them instead of one fixed key:

- ``caller_context``: ``CallerContext`` and the ``ACTIVE_CALLER`` /
  ``ACTIVE_AGENT`` context variables (set by ``BaseOrchestrator.execute_squads()``
  and the ``BaseAgent`` wrapper).
- ``subject_token_store``: where ``admit()`` keeps the person's token, server
  side, under a random reference carried in the signed identity stamp. The
  token itself never travels in a payload or a Kafka event.
- ``base_credential_broker``: ``BaseCredentialBroker``, the ABB that turns the
  caller into request headers for one audience (OOB:
  ``TokenExchangeCredentialBroker``, OAuth 2.0 token exchange, RFC 8693).

Design: ``docs/roadmap/on-behalf-of-design.md``.
"""
