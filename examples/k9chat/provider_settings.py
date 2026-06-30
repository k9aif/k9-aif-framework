# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat runtime provider settings
#
# Lets the UI point k9chat at a different LLM host/provider/model at
# runtime, without touching config.yaml on disk. An API key typed into
# the browser is held in os.environ for this process only — it is
# never written to config.yaml or any file, matching the framework's
# "no credentials in config files" rule.

import os
from typing import List, Optional

import requests

RUNTIME_API_KEY_ENV = "K9CHAT_RUNTIME_API_KEY"

SUPPORTED_PROVIDERS = ("ollama", "openai-compatible")


def list_models(provider: str, base_url: str, api_key: Optional[str] = None, timeout: float = 8.0) -> List[str]:
    """Query the given host for its available models. Raises ValueError with a clear message on failure."""
    provider = (provider or "ollama").lower()
    base_url = (base_url or "").rstrip("/")

    if provider == "ollama":
        url = f"{base_url}/api/tags"
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Cannot reach Ollama at {base_url}: {exc}")
        if resp.status_code != 200:
            raise ValueError(f"Ollama at {base_url} returned HTTP {resp.status_code}")
        data = resp.json()
        return sorted(m["name"] for m in data.get("models", []))

    if provider == "openai-compatible":
        url = f"{base_url}/models" if base_url else "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Cannot reach {url}: {exc}")
        if resp.status_code != 200:
            raise ValueError(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return sorted(m["id"] for m in data.get("data", []))

    raise ValueError(f"Unsupported provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}")


def build_overrides(provider: str, base_url: str, model: str, api_key: Optional[str] = None) -> dict:
    """
    Build a config override dict for inference.llm_factory, and stash any
    typed API key in this process's environment (never on disk).
    """
    provider = (provider or "ollama").lower()
    overrides = {
        "provider": provider,
        "backend": provider,
        "base_url": base_url,
        "models": {"general": model},
    }

    if provider == "openai-compatible":
        if api_key:
            os.environ[RUNTIME_API_KEY_ENV] = api_key
            overrides["api_key_env"] = RUNTIME_API_KEY_ENV
        else:
            os.environ.pop(RUNTIME_API_KEY_ENV, None)

    return overrides
