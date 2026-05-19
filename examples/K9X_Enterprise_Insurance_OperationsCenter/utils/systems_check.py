# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/systems_check.py (SBB)

from __future__ import annotations

from typing import Any, Dict
import logging
import os
import shutil

log = logging.getLogger(__name__)


class SystemCheckError(Exception):
    """Raised when a critical system dependency check fails."""


def run_system_checks(config: Dict[str, Any] | None = None) -> bool:
    """
    Run all EOC pre-flight system checks.

    Checks: config structure, runtime directories, OCR tool availability,
    LLM reachability (soft), messaging connectivity (soft), storage (soft).

    Args:
        config: The loaded application config dict.

    Returns:
        True if all checks pass, False otherwise.
    """
    log.info("--------------------------------------------------")
    log.info("Running K9X EOC pre-flight system checks...")
    log.info("--------------------------------------------------")

    config = config or {}

    results = {
        "config": _check_config(config),
        "environment": _check_environment(config),
        "ocr_tool": _check_ocr_tool(config),
        "llm": _check_llm(config),
        "messaging": _check_messaging(config),
        "storage": _check_storage(config),
        "neo4j": _check_neo4j(config),
    }

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        log.error("System checks failed: %s", failed)
        return False

    log.info("All EOC system checks passed.")
    return True


def _check_config(config: Dict[str, Any]) -> bool:
    try:
        app = config.get("app", {})
        app_name = app.get("name") if isinstance(app, dict) else None
        if not app_name:
            app_name = config.get("app_name", "K9X_EOC")
            log.warning("app.name missing in config, using fallback: %s", app_name)
        else:
            log.info("Config OK — app: %s", app_name)

        eoc = config.get("eoc", {})
        log.info("EOC confidence threshold: %s", eoc.get("confidence_threshold", 0.75))
        log.info("EOC environment: %s", config.get("runtime", {}).get("environment", "dev"))
        return True
    except Exception as exc:
        log.error("Config check failed: %s", exc)
        return False


def _check_environment(config: Dict[str, Any]) -> bool:
    try:
        runtime = config.get("runtime", {})
        for dir_key in ("workspace_dir", "temp_dir", "audit_db_dir"):
            d = runtime.get(dir_key)
            if d:
                os.makedirs(d, exist_ok=True)
                log.info("Directory ready: %s = %s", dir_key, d)
        return True
    except Exception as exc:
        log.error("Environment check failed: %s", exc)
        return False


def _check_ocr_tool(config: Dict[str, Any]) -> bool:
    tools = config.get("tools", {})
    ocr_cfg = tools.get("tesseract", {}) if isinstance(tools, dict) else {}
    enabled = ocr_cfg.get("enabled", True) if isinstance(ocr_cfg, dict) else True

    if not enabled:
        log.info("OCR (Tesseract) disabled in config — skipping check.")
        return True

    if shutil.which("tesseract"):
        log.info("OCR tool: tesseract found.")
        return True

    log.warning(
        "Tesseract not found in PATH. DocumentExtractorAgent will fall back to LLM-only extraction. "
        "Install tesseract-ocr for full OCR support."
    )
    return True  # soft warning, not a hard failure


def _check_llm(config: Dict[str, Any]) -> bool:
    log.info("LLM check: deferred to runtime (Ollama connectivity verified on first call).")
    return True


def _check_messaging(config: Dict[str, Any]) -> bool:
    messaging = config.get("messaging", {})
    if not messaging:
        log.info("No messaging config found — event bus disabled.")
        return True
    log.info(
        "Messaging: provider=%s broker=%s (connectivity verified at runtime)",
        messaging.get("provider", "redpanda"),
        messaging.get("bootstrap_servers", "localhost:9092"),
    )
    return True


def _check_storage(config: Dict[str, Any]) -> bool:
    storage = config.get("storage", {})
    if not storage:
        log.info("No storage config — using SQLite audit DB (local mode).")
        return True
    log.info(
        "Storage: DB connectivity will be verified on first transaction (host=%s).",
        storage.get("host", "localhost"),
    )
    return True


def _check_neo4j(config: Dict[str, Any]) -> bool:
    graph = config.get("graph", {})
    enabled = graph.get("graph_sync_enabled", False) if isinstance(graph, dict) else False
    if not enabled:
        log.info("Neo4j graph sync disabled — GraphSyncAgent will skip sync operations.")
        return True
    log.info(
        "Neo4j: uri=%s (connectivity verified on first sync)",
        graph.get("uri", "bolt://localhost:7687"),
    )
    return True
