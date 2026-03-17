from __future__ import annotations

from typing import Any, Dict
import logging
import os


log = logging.getLogger(__name__)


class SystemCheckError(Exception):
    """Raised when a required system dependency check fails."""


def run_system_checks(config: Dict[str, Any] | None = None) -> bool:
    log.info("--------------------------------------------------")
    log.info("Running ACME Support Center pre-flight checks...")
    log.info("--------------------------------------------------")

    config = config or {}

    results = {
        "config": check_config(config),
        "tools": check_tools(config),
        "environment": check_environment(config),
        "llm": check_llm(config),
        "messaging": check_messaging(config),
        "storage": check_storage(config),
    }

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        log.error("One or more system checks failed: %s", failed)
        return False

    log.info("All system checks passed.")
    return True


def check_config(config: Dict[str, Any]) -> bool:
    try:
        app = config.get("app", {})
        runtime = config.get("runtime", {})
        router = config.get("router", {})

        app_name = None
        if isinstance(app, dict):
            app_name = app.get("name") or app.get("app_name")

        if not app_name:
            app_name = config.get("app_name") or config.get("name") or "acme_support_center"
            log.warning("app.name missing in config. Using fallback app name: %s", app_name)
        else:
            log.info("Config loaded for app: %s", app_name)

        log.info("Runtime environment: %s", runtime.get("environment", "dev"))
        log.info("Default squad: %s", router.get("default_squad", "support_squad"))
        return True

    except Exception as exc:
        log.error("Config check failed: %s", exc)
        return False


def check_tools(config: Dict[str, Any]) -> bool:
    try:
        tools = config.get("tools", {})
        if not isinstance(tools, dict):
            log.warning("tools section is not a dictionary. Skipping strict tool validation.")
            return True

        log.info("Configured tools: %s", list(tools.keys()))

        expected_tools = {"ticket_tool", "knowledge_retriever"}
        missing = expected_tools - set(tools.keys())
        if missing:
            log.warning("Missing expected tools: %s", sorted(missing))

        return True

    except Exception as exc:
        log.error("Tools check failed: %s", exc)
        return False


def check_environment(config: Dict[str, Any]) -> bool:
    try:
        runtime = config.get("runtime", {})
        workspace_dir = runtime.get("workspace_dir")
        temp_dir = runtime.get("temp_dir")

        if workspace_dir:
            os.makedirs(workspace_dir, exist_ok=True)
            log.info("Workspace dir ready: %s", workspace_dir)

        if temp_dir:
            os.makedirs(temp_dir, exist_ok=True)
            log.info("Temp dir ready: %s", temp_dir)

        return True

    except Exception as exc:
        log.error("Environment check failed: %s", exc)
        return False


def check_llm(config: Dict[str, Any]) -> bool:
    log.info("Skipping LLM check for simple mode.")
    return True


def check_messaging(config: Dict[str, Any]) -> bool:
    log.info("Skipping messaging check for simple mode.")
    return True


def check_storage(config: Dict[str, Any]) -> bool:
    log.info("Skipping storage check for simple mode.")
    return True