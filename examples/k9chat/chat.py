# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import copy
import os
import sys
import uuid

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
from k9_aif_abb.k9_factories.cache_factory import CacheFactory
from examples.k9chat.chat_agent import ChatAgent
from examples.k9chat.health_check import check_ollama_model, run_startup_check
from examples.k9chat import provider_settings
from examples.k9chat.project_manager import ProjectManager, ProjectNotFoundError, build_persistence
from examples.k9chat.project_retriever import ProjectRetriever

log = logging.getLogger(__name__)

_AGENT = None
_CONFIG = None
_LLM_OVERRIDES = None  # set via apply_settings() — never persisted to disk
_EVAL_ENABLED = False
_EVALUATOR = None
_PROJECT_MANAGER = None
_PROJECT_RETRIEVER = None


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


def get_project_manager() -> ProjectManager:
    global _PROJECT_MANAGER
    if _PROJECT_MANAGER is None:
        persistence = build_persistence(load_config())
        _PROJECT_MANAGER = ProjectManager(persistence)
    return _PROJECT_MANAGER


def get_project_retriever() -> ProjectRetriever:
    global _PROJECT_RETRIEVER
    if _PROJECT_RETRIEVER is None:
        _PROJECT_RETRIEVER = ProjectRetriever(load_config())
    return _PROJECT_RETRIEVER


def _resolve_project_context(project_id: str | None, message: str) -> tuple[str, list]:
    """Look up a project's instructions + retrieve relevant file chunks
    for this message. Returns ("", []) if no project_id, the project
    doesn't exist, or nothing relevant is found -- callers always get a
    safe pair to pass straight into ChatAgent, never need to branch on
    project_id being present themselves."""
    if not project_id:
        return "", []
    project = get_project_manager().get_project(project_id)
    if project is None:
        return "", []
    instructions = project.get("instructions", "")
    context = []
    if project.get("file_ids"):
        context = get_project_retriever().retrieve_context(project_id, message, top_k=5)
    return instructions, context


def send_message(text: str, session_id: str = "default", project_id: str | None = None) -> str:
    agent = build_chat_agent()
    instructions, context = _resolve_project_context(project_id, text)
    result = agent.execute({
        "text": text,
        "session_id": session_id,
        "project_instructions": instructions,
        "project_context": context,
    })
    return result.get("text", "")


def is_streaming_enabled() -> bool:
    config = load_config()
    return bool(config.get("chat", {}).get("stream", False))


async def send_message_stream(text: str, session_id: str = "default", project_id: str | None = None):
    """Yield response chunks as they arrive — used when chat.stream: true."""
    agent = build_chat_agent()
    instructions, context = _resolve_project_context(project_id, text)
    async for chunk in agent.execute_stream({
        "text": text,
        "session_id": session_id,
        "project_instructions": instructions,
        "project_context": context,
    }):
        yield chunk


def clear_session(session_id: str) -> None:
    agent = build_chat_agent()
    agent.clear_history(session_id)


# ── Projects ─────────────────────────────────────────────────────────────────

def create_project(name: str, instructions: str = "") -> dict:
    return get_project_manager().create_project(name, instructions)


def list_projects() -> list:
    return get_project_manager().list_projects()


def get_project(project_id: str) -> dict | None:
    return get_project_manager().get_project(project_id)


def update_project(project_id: str, name: str | None = None, instructions: str | None = None) -> dict:
    return get_project_manager().update_project(project_id, name, instructions)


def delete_project(project_id: str) -> dict:
    """Delete the project record, then every file's chunks/embeddings --
    in that order would orphan vectors if this crashed mid-way, so do
    retrieval-store cleanup first, metadata second: an orphaned metadata
    record pointing at deleted vectors is a visible, harmless no-op on
    next read; orphaned vectors with no metadata record are invisible and
    unrecoverable clutter that would just sit in ChromaDB's collection
    forever, so eliminating the vectors is the fail-safe side."""
    manager = get_project_manager()
    file_chunk_counts = manager.delete_project(project_id)
    if file_chunk_counts:
        get_project_retriever().delete_project(project_id, file_chunk_counts)
    return {"deleted": project_id}


def add_project_file(project_id: str, filename: str, text: str) -> dict:
    """Chunk + embed + store the file's content, then record it against
    the project. Raises ProjectNotFoundError if project_id doesn't exist
    (checked via get_project up front, before doing any embedding work --
    no point calling Ollama for a project that isn't there)."""
    manager = get_project_manager()
    if manager.get_project(project_id) is None:
        raise ProjectNotFoundError(project_id)

    file_id = str(uuid.uuid4())
    retriever = get_project_retriever()
    chunk_count = retriever.add_file(project_id, file_id, filename, text)
    return manager.add_file(project_id, file_id, filename, chunk_count)


def remove_project_file(project_id: str, file_id: str) -> dict:
    manager = get_project_manager()
    chunk_count = manager.remove_file(project_id, file_id)
    get_project_retriever().remove_file(project_id, file_id, chunk_count)
    return manager.get_project(project_id)


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
        # Friendly name for the inference host, e.g. "PowerAI-5090" --
        # purely cosmetic (never used for routing/connection), same
        # OLLAMA_DISPLAY_NAME convention dow-k9-aif's DAS already uses.
        "display_name": os.environ.get("OLLAMA_DISPLAY_NAME", ""),
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