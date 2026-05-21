#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — Orchestrator Process (Container 3: eoc_orchestrator)
#
# Async Kafka consumer (aiokafka via K9EventBus) that reads from all seven
# domain topics, dispatches each event to EOCOrchestrator (squads + agents),
# and publishes the result to `eoc-results` via K9EventBus.
#
# Production flow:
#   eoc-claims / eoc-fraud / …  →  K9EventBus.subscribe_async
#                               →  EOCOrchestrator.execute_flow()
#                               →  K9EventBus (results)  →  eoc-results
#
# Usage:
#   python -m examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator_process
#
# Environment:
#   K9_KAFKA_BROKERS  — comma-separated broker list (default: localhost:9092)

import asyncio
import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_core.messaging.k9_event_bus import K9EventBus
from examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator import EOCOrchestrator
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.llm_invoke import register_sse_callback as register_llm_invoke_sse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger("eoc.orchestrator_process")

DOMAIN_TOPICS = [
    "eoc-claims",
    "eoc-documents",
    "eoc-fraud",
    "eoc-policy",
    "eoc-catastrophe",
    "eoc-customer",
    "eoc-audit",
]
RESULTS_TOPIC = "eoc-results"
GROUP_ID      = "eoc-orchestrator"


def _load_config() -> dict:
    try:
        return load_yaml(
            "examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml"
        )
    except Exception as exc:
        log.warning("Config load skipped: %s", exc)
        return {}


async def main() -> None:
    config = _load_config()

    brokers_raw = (
        os.environ.get("K9_KAFKA_BROKERS")
        or ",".join(config.get("messaging", {}).get("brokers", ["localhost:9092"]))
    )
    brokers = [b.strip() for b in brokers_raw.split(",") if b.strip()]
    broker  = brokers[0]

    log.info("[OrchestratorProcess] Loading EOCOrchestrator (all squads) …")
    orchestrator = EOCOrchestrator(config=config)
    log.info(
        "[OrchestratorProcess] Ready | handlers=%d | broker=%s",
        len(orchestrator._handlers), broker,
    )

    # K9EventBus ABB — results publisher
    results_bus = K9EventBus(
        broker_url=broker,
        topic=RESULTS_TOPIC,
        group_id=GROUP_ID,
    )

    # Forward LLMCall trace events to the API server via the results topic.
    def _kafka_llm_push(event: dict) -> None:
        try:
            results_bus.publish(event)
        except Exception as exc:
            log.warning("[OrchestratorProcess] LLMCall Kafka push failed: %s", exc)

    register_llm_invoke_sse(_kafka_llm_push)

    # K9EventBus ABB — inbound consumer (all domain topics via subscribe_async)
    inbound_bus = K9EventBus(
        broker_url=broker,
        topic=DOMAIN_TOPICS[0],
        group_id=GROUP_ID,
    )

    async def handle(payload: dict) -> None:
        event_type = payload.get("event_type", "")
        event_id   = payload.get("event_id",   "")
        corr       = payload.get("correlation_id", "")
        print(
            f"\n  ◀ ORCHESTRATOR  CONSUME  event_type='{event_type}'  corr={corr}\n",
            flush=True,
        )
        try:
            result   = await orchestrator.execute_flow(payload)
            status   = result.get("status", "?")
            decision = result.get("final_decision") or result.get("decision") or ""
            print(
                f"  ✓ ORCHESTRATOR  DONE  event_type='{event_type}'  status='{status}'"
                f"  decision='{decision}'  →  '{RESULTS_TOPIC}'\n",
                flush=True,
            )
            results_bus.publish({
                "event_type":     event_type,
                "event_id":       event_id,
                "correlation_id": corr,
                "result":         result,
            })
        except Exception as exc:
            log.error(
                "[OrchestratorProcess] Pipeline error event_type=%s: %s",
                event_type, exc, exc_info=True,
            )
            results_bus.publish({
                "event_type":     event_type,
                "event_id":       event_id,
                "correlation_id": corr,
                "result":         {"status": "error", "detail": str(exc)},
            })

    log.info(
        "[OrchestratorProcess] Starting K9EventBus async consumer on %d domain topics …",
        len(DOMAIN_TOPICS),
    )
    try:
        await inbound_bus.subscribe_async(
            handle,
            topics=DOMAIN_TOPICS,
            session_timeout_ms=60000,
            heartbeat_interval_ms=20000,
            max_poll_interval_ms=600000,
        )
    finally:
        results_bus.close()
        log.info("[OrchestratorProcess] Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[OrchestratorProcess] Shutdown requested.")
    except Exception as exc:
        log.error("[OrchestratorProcess] Fatal: %s", exc, exc_info=True)
