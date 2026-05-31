# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/systems_check.py
# -----------------------------------------------------------
# Pre-flight checks for all critical EOC dependencies.
# Called at startup — if any check fails the app will not start.

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import urllib.request
import urllib.error
from typing import Any, Dict

log = logging.getLogger(__name__)


# -----------------------------------------------------------
# Ollama / LLM backend
# -----------------------------------------------------------
def check_llm(config: Dict[str, Any]) -> bool:
    log.info("Checking LLM backend (Ollama)...")
    try:
        llm_cfg  = config.get("inference", {}).get("llm_factory", {})
        base_url = llm_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        models   = llm_cfg.get("models", {})

        # 1. Server reachable + model list
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as r:
            tags = json.loads(r.read())

        loaded   = {m.get("name", "").split(":")[0] for m in tags.get("models", [])}
        required = {v.get("model", "").split(":")[0] for v in models.values() if v.get("model")}
        missing  = required - loaded
        if missing:
            log.error("Ollama models not loaded: %s — run: ollama pull <model>", sorted(missing))
            return False

        log.info("Ollama server reachable at %s — %d model(s) loaded", base_url, len(loaded))

        # 2. Warm-up inference — send "ping" to every configured model so they
        #    are loaded into GPU memory before the first real request arrives.
        #    This prevents multi-second cold-start delays on first scenario run.
        for alias, mcfg in models.items():
            model_name = mcfg.get("model", "")
            if not model_name:
                continue
            log.info("Warming up model alias=%s model=%s ...", alias, model_name)
            body = json.dumps({"model": model_name, "prompt": "ping", "stream": False}).encode()
            req  = urllib.request.Request(
                f"{base_url}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
            text = resp.get("response", "").strip()
            if not text:
                log.error("Ollama warm-up returned empty response for model %s", model_name)
                return False
            log.info("Warm-up OK — alias=%s model=%s response_len=%d chars", alias, model_name, len(text))

        return True

    except urllib.error.URLError as exc:
        log.error("Ollama unreachable: %s", exc)
        return False
    except Exception as exc:
        log.error("LLM check failed: %s", exc)
        return False


# -----------------------------------------------------------
# Postgres
# -----------------------------------------------------------
def check_postgres(config: Dict[str, Any]) -> bool:
    log.info("Checking Postgres...")
    pg = config.get("postgres", {})
    host = pg.get("host", "localhost")
    port = int(pg.get("port", 5432))
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
    except Exception as exc:
        log.error("Postgres port unreachable at %s:%d — %s", host, port, exc)
        return False

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=host, port=port,
            user=pg.get("user", "postgres"),
            password=pg.get("password", ""),
            dbname=pg.get("database", "eoc"),
            connect_timeout=5,
            options=f"-c search_path={pg.get('schema', 'eoc')},public",
        )
        conn.close()
        log.info("Postgres reachable at %s:%d db=%s schema=%s", host, port,
                 pg.get("database", "eoc"), pg.get("schema", "eoc"))
        return True
    except ImportError:
        log.warning("psycopg2 not installed — skipping auth check (port %s:%d is open)", host, port)
        return True
    except Exception as exc:
        log.error("Postgres auth/schema check failed: %s", exc)
        return False


# -----------------------------------------------------------
# Neo4j
# -----------------------------------------------------------
def check_neo4j(config: Dict[str, Any]) -> bool:
    log.info("Checking Neo4j...")
    import os
    neo4j_cfg = config.get("neo4j", {})
    uri      = neo4j_cfg.get("uri", "bolt://localhost:7687")
    user     = neo4j_cfg.get("user", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1 AS ok").single()
        driver.close()
        log.info("Neo4j reachable at %s", uri)
        return True
    except ImportError:
        log.warning("neo4j driver not installed — skipping Neo4j check")
        return True
    except Exception as exc:
        log.error("Neo4j check failed (%s): %s", uri, exc)
        return False


# -----------------------------------------------------------
# Kafka / Redpanda (only when K9_KAFKA_MODE=1)
# -----------------------------------------------------------
def check_kafka(config: Dict[str, Any]) -> bool:
    if os.environ.get("K9_KAFKA_MODE", "").strip() not in ("1", "true", "yes"):
        log.info("Kafka mode disabled — skipping broker check")
        return True

    log.info("Checking Kafka broker(s)...")
    brokers_raw = (
        os.environ.get("K9_KAFKA_BROKERS")
        or ",".join(config.get("messaging", {}).get("brokers", ["localhost:9092"]))
    )
    all_ok = True
    for b in brokers_raw.split(","):
        b = b.strip()
        if not b:
            continue
        host, _, port_s = b.rpartition(":")
        try:
            s = socket.create_connection((host, int(port_s or 9092)), timeout=5)
            s.close()
            log.info("Kafka broker reachable at %s", b)
        except Exception as exc:
            log.error("Kafka broker unreachable at %s — %s", b, exc)
            all_ok = False
    return all_ok


# -----------------------------------------------------------
# OCR tool (soft warning, never blocks startup)
# -----------------------------------------------------------
def check_ocr() -> bool:
    if shutil.which("tesseract"):
        log.info("OCR: tesseract found in PATH")
    else:
        log.warning(
            "OCR: tesseract not found — DocumentExtractorAgent will use LLM-only extraction. "
            "Install tesseract-ocr for full OCR support."
        )
    return True  # non-critical


# -----------------------------------------------------------
# Run all checks
# -----------------------------------------------------------
def run_all_checks(config: Dict[str, Any] | None = None) -> bool:
    config = config or {}
    log.info("--------------------------------------------------")
    log.info("K9X EOC pre-flight system checks starting...")
    log.info("--------------------------------------------------")

    results = {
        "llm":      check_llm(config),
        "postgres": check_postgres(config),
        "neo4j":    check_neo4j(config),
        "kafka":    check_kafka(config),
        "ocr":      check_ocr(),
    }

    failed = [name for name, ok in results.items() if not ok]

    log.info("--------------------------------------------------")
    for name, ok in results.items():
        log.info("  %-12s %s", name.upper(), "✓ OK" if ok else "✗ FAILED")
    log.info("--------------------------------------------------")

    if failed:
        log.error("System checks FAILED: %s — EOC will not start.", failed)
        return False

    log.info("All systems operational. EOC ready to initialize.")
    return True


if __name__ == "__main__":
    import sys
    from k9_aif_abb.k9_utils.config_loader import load_yaml
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_yaml("examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml")
    sys.exit(0 if run_all_checks(cfg) else 1)
