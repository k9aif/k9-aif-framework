# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import copy
import os
import sys

from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

BASE_DIR = os.path.dirname(__file__)

# python-dotenv's load_dotenv() (called by config_loader below) searches
# upward from k9_aif_abb/'s location and only ever finds the repo-root
# .env. Load this example's own .env on top so OLLAMA_BASE_URL etc. can
# live alongside k9chat instead of requiring edits to the shared root .env.
load_dotenv(os.path.join(BASE_DIR, ".env"))

import logging

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_factories.evaluation_factory import EvaluationFactory
from examples.k9chat.chat_agent import ChatAgent
from examples.k9chat.health_check import check_ollama_model, run_startup_check
from examples.k9chat import provider_settings

log = logging.getLogger(__name__)

_AGENT = None
_CONFIG = None
_LLM_OVERRIDES = None  # set via apply_settings() — never persisted to disk
_EVAL_ENABLED = False
_EVALUATOR = None


def load_config() -> dict:
    global _CONFIG
    if _CONFIG is None:
        base = load_yaml(os.path.join(BASE_DIR, "config.yaml"))
        if _LLM_OVERRIDES:
            base = copy.deepcopy(base)
            base.setdefault("inference", {}).setdefault("llm_factory", {}).update(_LLM_OVERRIDES)
        _CONFIG = base
    return _CONFIG


def build_chat_agent():
    """
    Construct ChatAgent with the merged runtime config (config.yaml + any
    settings-panel overrides). Built directly rather than via
    SquadLoader/AgentRegistry — those construct agents with no-arg
    ``create(name)``, which would silently drop our overrides since
    ChatAgent() then falls back to re-reading config.yaml fresh from disk.
    """
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    _AGENT = ChatAgent(load_config())
    return _AGENT


def send_message(text: str, session_id: str = "default") -> str:
    agent = build_chat_agent()
    result = agent.execute({"text": text, "session_id": session_id})
    return result.get("text", "")


def is_streaming_enabled() -> bool:
    config = load_config()
    return bool(config.get("chat", {}).get("stream", False))


async def send_message_stream(text: str, session_id: str = "default"):
    """Yield response chunks as they arrive — used when chat.stream: true."""
    agent = build_chat_agent()
    async for chunk in agent.execute_stream({"text": text, "session_id": session_id}):
        yield chunk


def clear_session(session_id: str) -> None:
    agent = build_chat_agent()
    agent.clear_history(session_id)


def list_models_for(provider: str, base_url: str, api_key: str = "") -> list:
    """Live model lookup against an arbitrary host — used by the settings UI."""
    return provider_settings.list_models(provider, base_url, api_key or None)


def apply_settings(provider: str, base_url: str, model: str, api_key: str = "") -> dict:
    """
    Repoint k9chat at a different provider/host/model at runtime.
    Resets the LLM + router factories and rebuilds the agent on next use.
    Never writes to config.yaml — the API key (if any) lives only in os.environ.
    """
    global _LLM_OVERRIDES, _CONFIG, _AGENT

    _LLM_OVERRIDES = provider_settings.build_overrides(provider, base_url, model, api_key)
    _CONFIG = None
    _AGENT = None
    LLMFactory.reset()
    ModelRouterFactory.reset()

    return get_health_status()


def get_chat_runtime_info() -> dict:
    config = load_config()

    inference_cfg = config.get("inference", {})
    llm_factory_cfg = inference_cfg.get("llm_factory", {})
    models = llm_factory_cfg.get("models", {})

    return {
        "provider": llm_factory_cfg.get("provider", "unknown"),
        "base_url": llm_factory_cfg.get("base_url", "unknown"),
        "model": models.get("general", "unknown"),
    }


def get_health_status() -> dict:
    """Live check — is the configured host reachable and is the model available?"""
    runtime = get_chat_runtime_info()

    if runtime["provider"] == "ollama":
        error = check_ollama_model(runtime["base_url"], runtime["model"])
    else:
        try:
            models = provider_settings.list_models(
                runtime["provider"], runtime["base_url"],
                os.environ.get(provider_settings.RUNTIME_API_KEY_ENV),
            )
            error = None if runtime["model"] in models else (
                f"Model '{runtime['model']}' not found at {runtime['base_url']}. "
                f"Available: {', '.join(models) or '(none)'}"
            )
        except ValueError as exc:
            error = str(exc)

    return {
        "ok": error is None,
        "provider": runtime["provider"],
        "base_url": runtime["base_url"],
        "model": runtime["model"],
        "error": error,
    }


def run_chat_startup_check() -> None:
    """Call once at app startup — prints a clear PASS/FAIL banner."""
    run_startup_check(load_config())


# ── Prompt Evaluation ──────────────────────────────────────────────────────────

def is_evaluation_enabled() -> bool:
    return _EVAL_ENABLED


def toggle_evaluation() -> bool:
    global _EVAL_ENABLED, _EVALUATOR
    _EVAL_ENABLED = not _EVAL_ENABLED
    if not _EVAL_ENABLED:
        _EVALUATOR = None
    return _EVAL_ENABLED


def evaluate_response(user_message: str, actual_output: str) -> dict | None:
    global _EVALUATOR
    if not _EVAL_ENABLED:
        return None
    try:
        if _EVALUATOR is None:
            _EVALUATOR = EvaluationFactory.create(load_config())
        result = _EVALUATOR.evaluate(
            prompt=user_message,
            input_data={"message": user_message},
            actual_output=actual_output,
            expected=(
                "Respond helpfully, accurately, and clearly to the user's question. "
                "Stay on topic, be concise, and avoid irrelevant content."
            ),
        )
        return {
            "score": round(result.score, 1),
            "grade": result.grade,
            "verdict": result.verdict,
            "rationale": result.rationale,
        }
    except Exception as exc:
        log.warning("[Evaluation] Failed: %s", exc)
        return None