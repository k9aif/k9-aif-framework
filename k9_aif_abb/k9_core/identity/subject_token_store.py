# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Where ``BaseRouter.admit()`` keeps the caller's own token (1.36.0).

The token stays server side. Only a random reference goes into the signed
identity stamp, so a payload, a log line or a Kafka event (kept for days,
readable by every consumer of the topic) never carries a live bearer token.

Backed by any ``BaseCache`` from ``CacheFactory``: ``in_memory`` (default)
when the router and the orchestrator run in one process, ``redis`` when they
run in separate processes. Entries expire with the identity stamp.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, Optional

_KEY_PREFIX = "k9:subject_token:"


class SubjectTokenStore:

    def __init__(self, cache: Any) -> None:
        if cache is None:
            raise ValueError("SubjectTokenStore needs a cache (BaseCache)")
        self._cache = cache

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]]) -> "SubjectTokenStore":
        """``security.on_behalf_of.token_store``: ``{provider: in_memory | redis, ...}``
        (the remaining keys go to the cache adapter)."""
        from k9_aif_abb.k9_factories.cache_factory import CacheFactory
        cfg = dict(cfg or {})
        provider = str(cfg.pop("provider", "in_memory"))
        return cls(CacheFactory.get(provider, cfg))

    def put(self, token: str, ttl_seconds: int) -> str:
        if not token:
            raise ValueError("SubjectTokenStore.put() needs a token")
        ref = secrets.token_urlsafe(24)
        self._cache.set(_KEY_PREFIX + ref, token, ttl=int(ttl_seconds))
        return ref

    def get(self, ref: Optional[str]) -> Optional[str]:
        if not ref:
            return None
        return self._cache.get(_KEY_PREFIX + ref)

    def delete(self, ref: str) -> None:
        self._cache.delete(_KEY_PREFIX + ref)
