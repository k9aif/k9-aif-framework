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
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from examples.k9chat.chat_agent import ChatAgent
from examples.k9chat.health_check import check_ollama_model, run_startup_check
from examples.k9chat import provider_settings
from examples.k9chat.project_manager import ProjectManager, ProjectNotFoundError, build_persistence
from examples.k9chat.project_retriever import ProjectRetriever
from examples.k9chat.knowledge_retriever import KnowledgeRetriever
from examples.k9chat import correction_learner
from examples.k9chat import faq_shortcut

log = logging.getLogger(__name__)

_AGENT = None
_CONFIG = None
_LLM_OVERRIDES = None  # set via apply_settings() — never persisted to disk
_EVAL_ENABLED = False
_EVALUATOR = None
_PROJECT_MANAGER = None
_PROJECT_RETRIEVER = None
_KNOWLEDGE_RETRIEVER = None
_LEARNING_ENABLED = None  # lazy: seeded from config.yaml's correction_learning.enabled on first access
_FAQ_SHORTCUT_ENABLED = None  # lazy: seeded from config.yaml's faq_shortcut.enabled on first access


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


def get_knowledge_retriever() -> KnowledgeRetriever:
    global _KNOWLEDGE_RETRIEVER
    if _KNOWLEDGE_RETRIEVER is None:
        _KNOWLEDGE_RETRIEVER = KnowledgeRetriever(load_config())
    return _KNOWLEDGE_RETRIEVER


def _resolve_knowledge_context(message: str) -> list:
    """Always-on K9-AIF/K9X knowledge grounding -- unlike project context,
    this doesn't depend on the caller selecting anything. Returns [] (not
    an error) if the knowledge base hasn't been seeded yet or the vector
    backend isn't reachable, same fail-open behavior as project context."""
    return get_knowledge_retriever().retrieve(message, top_k=5)


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


def check_faq_shortcut(text: str, session_id: str = "default") -> dict | None:
    """Checks the FAQ/glossary retrieve-then-rerank shortcut (faq_shortcut.py)
    BEFORE any LLM call -- callers (app.py's /chat and /chat/stream) run
    this first and only fall through to send_message()/send_message_stream()
    if it returns None. When it fires, this persists the turn to history
    itself (send_message()/execute() never runs, so nothing else would).

    Gated on the runtime toggle (is_faq_shortcut_enabled()), not on
    faq_shortcut.py re-reading a static config value -- same split as
    learn_from_correction()/is_correction_learning_enabled().

    Uses its own larger, dedicated retrieval (top_k=25) rather than
    reusing _resolve_knowledge_context()'s top_k=5 -- confirmed live that
    5 (even 8) isn't enough recall for the curated FAQ/glossary chunk to
    reliably even be IN the candidate pool the reranker sees (a bi-encoder
    recall limit, not a reranking/ordering one -- reranking only fixes
    ordering among retrieved candidates, it can't surface one that was
    never retrieved). The curated corpus is small (~19 chunks between
    glossary.md and faq.md), so top_k=25 gets close to full recall of it
    at negligible extra cost (still just a vector search, no LLM/GPU call
    either way)."""
    if not is_faq_shortcut_enabled():
        return None
    shortcut_candidates = get_knowledge_retriever().retrieve(text, top_k=25)
    match = faq_shortcut.try_shortcut(load_config(), shortcut_candidates, text)
    if not match:
        return None

    agent = build_chat_agent()
    history = agent._get_history(session_id)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": match["answer"]})
    agent._save_history(session_id, history)
    return match


def send_message(
    text: str, session_id: str = "default", project_id: str | None = None,
    unhinged_level: int = 0, profanity_level: int = 0, length_level: int = 1,
) -> str:
    agent = build_chat_agent()
    instructions, context = _resolve_project_context(project_id, text)
    knowledge_context = _resolve_knowledge_context(text)
    result = agent.execute({
        "text": text,
        "session_id": session_id,
        "project_instructions": instructions,
        "project_context": context,
        "knowledge_context": knowledge_context,
        "unhinged_level": unhinged_level,
        "profanity_level": profanity_level,
        "length_level": length_level,
    })
    return result.get("text", "")


_STREAM_OVERRIDE: bool | None = None  # None = defer to config.yaml's chat.stream


def is_streaming_enabled() -> bool:
    if _STREAM_OVERRIDE is not None:
        return _STREAM_OVERRIDE
    config = load_config()
    return bool(config.get("chat", {}).get("stream", False))


def toggle_streaming() -> bool:
    """Runtime override, same pattern as toggle_evaluation() -- never
    written to config.yaml, resets to the file's own default on restart."""
    global _STREAM_OVERRIDE
    _STREAM_OVERRIDE = not is_streaming_enabled()
    return _STREAM_OVERRIDE


async def send_message_stream(
    text: str, session_id: str = "default", project_id: str | None = None,
    unhinged_level: int = 0, profanity_level: int = 0, length_level: int = 1,
):
    """Yield response chunks as they arrive — used when chat.stream: true."""
    agent = build_chat_agent()
    instructions, context = _resolve_project_context(project_id, text)
    knowledge_context = _resolve_knowledge_context(text)
    async for chunk in agent.execute_stream({
        "text": text,
        "session_id": session_id,
        "project_instructions": instructions,
        "project_context": context,
        "knowledge_context": knowledge_context,
        "unhinged_level": unhinged_level,
        "profanity_level": profanity_level,
        "length_level": length_level,
    }):
        yield chunk


def clear_session(session_id: str) -> None:
    agent = build_chat_agent()
    agent.clear_history(session_id)


def truncate_session(session_id: str, keep_count: int) -> None:
    agent = build_chat_agent()
    agent.truncate_history(session_id, keep_count)


def get_last_assistant_reply(session_id: str) -> str | None:
    """Peeks at this session's history for the most recent assistant turn
    -- callers grab this BEFORE sending a new message through the agent
    (which appends + saves the new turn), so it reflects what the
    assistant said right before whatever the user is about to send now."""
    agent = build_chat_agent()
    history = agent._get_history(session_id)
    for entry in reversed(history):
        if entry.get("role") == "assistant":
            return entry.get("content")
    return None


# ── Projects ─────────────────────────────────────────────────────────────────
# owner_id scopes Projects per visitor (see auth.py's guest identity) --
# None means "unscoped" (login disabled, or a legacy pre-scoping project),
# which stays visible to everyone rather than becoming orphaned.

def create_project(name: str, instructions: str = "", owner_id: str | None = None) -> dict:
    return get_project_manager().create_project(name, instructions, owner_id)


def list_projects(owner_id: str | None = None) -> list:
    return get_project_manager().list_projects(owner_id)


def get_project(project_id: str, owner_id: str | None = None) -> dict | None:
    return get_project_manager().get_project_for_owner(project_id, owner_id)


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


def get_selectable_models() -> list[str]:
    """The curated header dropdown's options -- a short, .env-defined
    allowlist for the casual/SaaS-style picker, distinct from the
    Provider Settings panel's free-form "fetch every model this host has
    pulled" approach. K9CHAT_GENERAL_MODEL (today's active default) is
    always included even if someone forgets to list it explicitly, so the
    dropdown never opens without its own current selection as an option."""
    raw = os.environ.get("K9CHAT_SELECTABLE_MODELS", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    default_model = os.environ.get("K9CHAT_GENERAL_MODEL", "qwen3.8:27b")
    if default_model not in models:
        models.insert(0, default_model)
    return models


def apply_settings(provider: str, base_url: str, model: str, api_key: str = "") -> dict:
    """
    Repoint k9chat at a different provider/host/model at runtime.
    Resets the LLM + router factories and rebuilds the agent on next use.
    Never writes to config.yaml — the API key (if any) lives only in os.environ.

    Warms the model up synchronously (a trivial real generate call) rather
    than leaving it to load lazily on the visitor's next real message --
    confirmed 2026-09-20 that "select a model, nothing visibly happens
    until your next question" reads as broken even though the switch
    itself was always real. This call blocking until the model is
    genuinely resident (`ollama ps` will show it) is the fix: the
    dropdown's whole point is to switch models, so switching should mean
    something the moment you do it, not on your next message.
    """
    global _LLM_OVERRIDES, _CONFIG, _AGENT

    _LLM_OVERRIDES = provider_settings.build_overrides(provider, base_url, model, api_key)
    _CONFIG = None
    _AGENT = None
    LLMFactory.reset()
    ModelRouterFactory.reset()

    status = get_health_status()
    if status["ok"]:
        try:
            agent = build_chat_agent()
            agent.router.invoke(InferenceRequest(prompt="Hi", task_type="chat"))
            status["warmed_up"] = True
        except Exception as exc:
            # Health check passed (model is pulled) but the real warm-up
            # call still failed -- surface it, don't silently claim ready.
            status["warmed_up"] = False
            status["warmup_error"] = str(exc)
    return status


_VERSION_CACHE: str | None = None


def get_k9chat_version() -> str:
    """Short git commit hash so the UI can answer "is this the deployment
    I just pushed" at a glance -- a hand-maintained version string would
    go stale immediately given how often this app changes.

    Two sources, in order:
    1. K9CHAT_VERSION env var -- set by the container build (build-run.sh
       captures the host's k9-aif-framework commit hash as a build-arg;
       the container has no .git of its own to inspect, only
       k9_aif_abb/ + examples/k9chat/ are copied in).
    2. A live `git rev-parse --short HEAD` against this checkout -- the
       fallback for local (non-container) dev via run_k9chat.sh, where
       .git is right there and always accurate, including uncommitted
       moves between commits.
    Returns "unknown" if neither source works (e.g. a container built
    without the build-arg, or git isn't on PATH)."""
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE

    env_version = os.environ.get("K9CHAT_VERSION", "").strip()
    if env_version:
        _VERSION_CACHE = env_version
        return _VERSION_CACHE

    try:
        import subprocess
        repo_root = os.path.abspath(os.path.join(BASE_DIR, "../.."))
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            _VERSION_CACHE = result.stdout.strip()
            return _VERSION_CACHE
    except Exception:
        pass

    _VERSION_CACHE = "unknown"
    return _VERSION_CACHE


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
    if is_faq_shortcut_enabled():
        from examples.k9chat import faq_reranker
        faq_reranker.warm_up()


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


# ── Correction Auto-Learning ────────────────────────────────────────────────

def is_correction_learning_enabled() -> bool:
    global _LEARNING_ENABLED
    if _LEARNING_ENABLED is None:
        _LEARNING_ENABLED = bool(
            load_config().get("correction_learning", {}).get("enabled", False)
        )
    return _LEARNING_ENABLED


def toggle_correction_learning() -> bool:
    global _LEARNING_ENABLED
    _LEARNING_ENABLED = not is_correction_learning_enabled()
    return _LEARNING_ENABLED


def learn_from_correction(
    prior_reply: str | None, new_message: str, session_id: str = "default"
) -> dict | None:
    """Single entry point app.py calls after every user message -- gated
    entirely by the runtime toggle above, not by correction_learner.py
    re-reading a static config value (see correction_learner.detect_correction's
    own docstring for why that split matters)."""
    if not is_correction_learning_enabled():
        return None
    return correction_learner.learn(
        load_config(),
        get_knowledge_retriever(),
        prior_reply,
        new_message,
        session_id=session_id,
    )


# ── FAQ Retrieve-then-Rerank Shortcut ────────────────────────────────────────

def is_faq_shortcut_enabled() -> bool:
    global _FAQ_SHORTCUT_ENABLED
    if _FAQ_SHORTCUT_ENABLED is None:
        _FAQ_SHORTCUT_ENABLED = bool(
            load_config().get("faq_shortcut", {}).get("enabled", False)
        )
    return _FAQ_SHORTCUT_ENABLED


def toggle_faq_shortcut() -> bool:
    global _FAQ_SHORTCUT_ENABLED
    _FAQ_SHORTCUT_ENABLED = not is_faq_shortcut_enabled()
    return _FAQ_SHORTCUT_ENABLED