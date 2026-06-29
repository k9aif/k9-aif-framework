# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
k9_core.cache — ABB cache contract layer.

Provides the abstract ``BaseCache`` contract with four methods:
``get``, ``set``, ``delete``, ``clear``.

Concrete adapters:

- ``InMemoryAdapter`` — thread-safe dict, no TTL (default, zero-config)
- ``RedisAdapter`` — Redis / Valkey, TTL-aware (production)

Provisioned via ``CacheFactory.create(config)`` — reads ``config["cache"]["provider"]``.

Used by chat agents to persist conversation history per session_id (see Skill 14),
and by any component needing fast key-value storage with config-driven backend swap.

Typical import::

    from k9_aif_abb.k9_factories.cache_factory import CacheFactory
    cache = CacheFactory.create(config)
    cache.set("chat:session123", history_json, ttl=3600)
"""

from k9_aif_abb.k9_core.cache.base_cache import BaseCache

__all__ = ["BaseCache"]
