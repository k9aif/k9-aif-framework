---
description: Scaffold a new K9-AIF provider adapter following the Provider Adapter Pattern (Skill 11). Pass the concern name and provider name.
---

# K9-AIF: Add Adapter

Scaffold a new provider adapter for an infrastructure concern (secret management, cache, storage, etc.) following the three-layer Provider Adapter Pattern: ABB contract → adapter → factory.

The user provides: `<ConcernName> <ProviderName>` (e.g. `Cache Redis` or `SecretManager Vault`).

## Three-layer structure to generate

```
k9_aif_abb/
  k9_core/<concern>/base_<concern>.py       ← ABB contract (if not already existing)
  k9_<concern>/adapters/<provider>_adapter.py  ← Concrete implementation
  k9_factories/<concern>_factory.py         ← Static factory (if not already existing)
```

### 1. ABB contract (only if it does not already exist)

```python
# k9_core/<concern>/base_<concern>.py
from abc import ABC, abstractmethod


class Base<ConcernName>(ABC):

    @abstractmethod
    def get(self, key: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        raise NotImplementedError
```

### 2. Provider adapter — with lazy import pattern (mandatory for optional dependencies)

```python
# k9_<concern>/adapters/<provider>_adapter.py
from k9_aif_abb.k9_core.<concern>.base_<concern> import Base<ConcernName>


class <Provider><ConcernName>Adapter(Base<ConcernName>):

    def __init__(self, config=None):
        self._config = config or {}
        self._client = None  # lazy — do NOT import at module level

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import <provider_package>
            self._client = <provider_package>.Client(
                url=self._config.get("<concern>", {}).get("url", ""),
            )
        except ImportError as exc:
            raise RuntimeError("pip install <provider_package> required") from exc

    def get(self, key: str) -> str:
        self._ensure_client()
        return self._client.get(key)

    def set(self, key: str, value: str) -> None:
        self._ensure_client()
        self._client.set(key, value)
```

### 3. Register in the factory's `_ensure_defaults()`

```python
# In k9_factories/<concern>_factory.py — add inside _ensure_defaults():
from k9_aif_abb.k9_<concern>.adapters.<provider>_adapter import <Provider><ConcernName>Adapter
<ConcernName>Factory._registry["<provider_lower>"] = <Provider><ConcernName>Adapter
```

### 4. Config YAML

```yaml
<concern>:
  provider: <provider_lower>
  url: "..."          # provider-specific — no credentials here
  # credentials always via environment variables, never in config.yaml
```

## Rules to follow (must hold for every adapter)
- Credentials **never** in `config.yaml` — use `os.environ.get("MY_KEY")` in the adapter.
- Optional packages: lazy import in `_ensure_client()`, raise `RuntimeError` with install hint.
- Factory `create(config)` always has a zero-config default — no config key required for the common case.
- All new code is purely additive — never modify existing ABB classes.
- Adapters accept `config=None` in `__init__` — the factory always passes `config=cfg`.
- Already-implemented adapter areas: `SecretManager` (Env, Vault, AWS, IBM) and `Cache` (InMemory, Redis). Check these before creating a new concern from scratch.
