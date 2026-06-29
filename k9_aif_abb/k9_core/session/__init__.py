"""
k9_core.session — Session Management ABB.

Provides durable, config-driven session state for multi-turn conversations
and agentic workflows. Session management is opt-in via ``session.enabled: true``
in config.yaml — when enabled, ``K9SessionManager`` handles the full lifecycle:

- ``on_session_start(user_id)`` — creates a new ``K9Session`` with auto-generated UUID
- ``on_session_get(session_id)`` — retrieves and touches (TTL refresh)
- ``on_session_update(session_id, delta)`` — merges context changes
- ``on_session_expire / on_session_destroy`` — lifecycle cleanup
- ``enrich_payload(session, payload)`` — injects session context into agent payloads

Storage is pluggable via ``SessionFactory``:

- ``RedisSessionStore`` — distributed, TTL-aware (production)
- ``SQLiteSessionStore`` — single-node, persistent
- ``InMemorySessionStore`` — process-local (testing)

Switch backends with one config line — no code changes.

For chat applications, combine with ``CacheFactory`` (Redis) to persist
conversation message history per session_id. See Skill 14 in SKILLS.md.
"""

from k9_aif_abb.k9_core.session.k9_session import K9Session, SessionStatus
from k9_aif_abb.k9_core.session.base_session_store import BaseSessionStore
from k9_aif_abb.k9_core.session.k9_session_manager import K9SessionManager
from k9_aif_abb.k9_core.session.session_registry import SessionRegistry

__all__ = [
    "K9Session",
    "SessionStatus",
    "BaseSessionStore",
    "K9SessionManager",
    "SessionRegistry",
]
