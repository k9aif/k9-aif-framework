# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat startup health check
#
# Verifies the Ollama host is reachable AND the configured model is
# actually pulled — a stale model name is a common setup mistake that
# otherwise surfaces as a cryptic [WARN] inside the chat response.

import logging
from typing import Optional

import requests

log = logging.getLogger("k9chat.health")


def check_ollama_model(base_url: str, model: str, timeout: float = 5.0) -> Optional[str]:
    """
    Returns None if the host is reachable and the model is pulled.
    Returns a human-readable error string otherwise.
    """
    setup_hint = (
        "Please set up examples/k9chat/.env with OLLAMA_BASE_URL pointing to "
        "your Ollama server (e.g. OLLAMA_BASE_URL=http://<your-host>:11434), "
        "or use the Provider Settings panel in the UI."
    )

    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.exceptions.ConnectionError:
        return f"Cannot reach Ollama at {base_url} — is it running? {setup_hint}"
    except requests.exceptions.Timeout:
        return f"Ollama at {base_url} did not respond within {timeout}s. {setup_hint}"
    except Exception as exc:
        return f"Ollama health check failed: {exc}. {setup_hint}"

    if resp.status_code != 200:
        return f"Ollama at {base_url} returned HTTP {resp.status_code}"

    try:
        data = resp.json()
        available = {m["name"] for m in data.get("models", [])}
    except Exception:
        return f"Ollama at {base_url} returned an unexpected response"

    # Ollama may report "llama3.2:1b" with or without an explicit ":latest"
    # suffix depending on version — match on the base name too.
    model_base = model.split(":")[0]
    if model in available or any(a.split(":")[0] == model_base and ":" in a for a in available):
        if model not in available:
            log.warning(
                "[k9chat] Configured model '%s' not found exactly, but a "
                "'%s' variant is pulled — proceeding.", model, model_base,
            )
        return None

    pulled = ", ".join(sorted(available)) or "(none)"
    return (
        f"Model '{model}' is not pulled on {base_url}.\n"
        f"  Pulled models: {pulled}\n"
        f"  Fix: ollama pull {model}"
    )


def run_startup_check(config: dict) -> None:
    """
    Logs a clear PASS/FAIL banner at startup. Does not raise — k9chat
    still starts so the error is visible in the UI/logs rather than
    blocking the process, but the warning is impossible to miss.
    """
    llm_cfg = config.get("inference", {}).get("llm_factory", {})
    base_url = llm_cfg.get("base_url", "http://localhost:11434")
    model = llm_cfg.get("models", {}).get("general", "")

    print("━" * 50)
    print("  K9Chat — Startup Health Check")
    print(f"  Ollama host : {base_url}")
    print(f"  Model       : {model}")

    error = check_ollama_model(base_url, model)
    if error:
        print("  Status      : ✗ FAILED")
        print(f"  {error}")
        log.error("[k9chat] Startup health check failed: %s", error)
    else:
        print("  Status      : ✓ OK — model is pulled and ready")
        log.info("[k9chat] Startup health check passed (%s @ %s)", model, base_url)

    print("━" * 50)
