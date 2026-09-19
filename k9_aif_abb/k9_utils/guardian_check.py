# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
guardian_check — startup-time check: does the Ollama endpoint a solution is
already configured to use actually have the Granite Guardian model pulled?

Distinct from (and doesn't require) GuardianGovernance actually being wired
into an agent — this is a pure connectivity/inventory check, useful the
moment a solution starts up, independent of whether semantic governance is
enabled yet. A solution's .env commonly already points OLLAMA_BASE_URL at
a real endpoint for its reasoning models; this checks whether that same
endpoint also has the guardian model, since it's easy to have general
inference models pulled and forget the guardian one, or vice versa.

Does not raise — callers decide what "not available" means for them
(hard-fail in production, warn in development, etc.), matching the
framework's existing policy-decision convention (see ShieldGovernance's
fail_open, GuardianGovernance's on_guardian_unavailable in k9x_satan).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger("governance.guardian_check")

DEFAULT_GUARDIAN_MODEL = "granite4.1-guardian:8b"


def check_guardian_available(
    ollama_base_url: str,
    guardian_model: str = DEFAULT_GUARDIAN_MODEL,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """
    Returns (available, message).

    available=True  — the endpoint is reachable and the named model is
                       in its pulled-model inventory.
    available=False — endpoint unreachable, or reachable but the model
                       isn't pulled. `message` explains which, with the
                       exact `ollama pull <model>` fix when applicable.
    """
    url = f"{ollama_base_url.rstrip('/')}/api/tags"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        return False, f"Ollama unreachable at {ollama_base_url}: {exc}"

    if not resp.ok:
        return False, f"Ollama at {ollama_base_url} returned HTTP {resp.status_code}"

    try:
        models = [m.get("name", "") for m in resp.json().get("models", [])]
    except (ValueError, AttributeError) as exc:
        return False, f"Ollama at {ollama_base_url} returned an unparseable /api/tags response: {exc}"

    if guardian_model in models:
        return True, f"Guardian model '{guardian_model}' available at {ollama_base_url}"

    return False, (
        f"Guardian model '{guardian_model}' not found on Ollama at {ollama_base_url} "
        f"(pulled models: {models or 'none'}). Fix: ollama pull {guardian_model}"
    )


def warn_if_guardian_unavailable(
    ollama_base_url: str,
    guardian_model: str = DEFAULT_GUARDIAN_MODEL,
    timeout: float = 5.0,
) -> bool:
    """
    Convenience wrapper for a startup banner: logs a clear WARNING (never
    raises) if the guardian model isn't available, logs INFO if it is.
    Returns the same `available` bool as check_guardian_available(), in
    case a caller wants to act on it (e.g. hard-fail in production).
    """
    available, message = check_guardian_available(ollama_base_url, guardian_model, timeout)
    if available:
        log.info("[GuardianCheck] %s", message)
    else:
        log.warning(
            "[GuardianCheck] Semantic governance (Granite Guardian) is NOT available — "
            "only k9x_Shield's deterministic pattern checks are active. %s",
            message,
        )
    return available
