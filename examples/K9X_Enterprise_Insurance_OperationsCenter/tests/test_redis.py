# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# Redis cache smoke test — exercises the CacheFactory -> RedisAdapter path,
# the same path an SBB agent uses via CacheFactory.create(self.config).
# Connection details come from env (.env); password is REDIS_PASSWORD only —
# never in config.yaml (see RedisAdapter docstring).

from dotenv import load_dotenv
import os

from k9_aif_abb.k9_factories.cache_factory import CacheFactory

load_dotenv()

config = {
    "cache": {
        "provider": "redis",
        "redis_host": os.getenv("REDIS_HOST", "localhost"),
        "redis_port": int(os.getenv("REDIS_PORT", "6379")),
        "key_prefix": "k9aif:eoc:",
    }
}

try:
    cache = CacheFactory.create(config)
    print(f"✓ CacheFactory created: {type(cache).__name__}")

    cache.set("greeting", "Hello from K9-AIF EOC Redis!", ttl=60)
    print("✓ set('greeting', ..., ttl=60)")

    value = cache.get("greeting")
    print(f"✓ get('greeting') -> {value!r}")

    print(f"✓ exists('greeting') -> {cache.exists('greeting')}")

    cache.delete("greeting")
    print(f"✓ delete('greeting') — exists now -> {cache.exists('greeting')}")

except Exception as e:
    print(f"Error: {type(e).__name__}")
    print(f"Details: {str(e)}")
