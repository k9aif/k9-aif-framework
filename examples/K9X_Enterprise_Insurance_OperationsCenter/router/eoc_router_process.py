#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — Router Process (Container 2: eoc_router)
#
# Async Kafka consumer (aiokafka via K9EventBus) that routes events
# from the inbound topic (`eoc-events`) to the correct domain topic.
#
# Production flow:
#   app_backend  →  eoc-events  →  K9EventBus.subscribe_async
#                               →  EOCRouter.route()
#                               →  K9EventBus producers  →  eoc-claims / eoc-fraud / …
#
# Usage:
#   python -m examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router_process
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
from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router import EOCRouter, _ROUTING_TABLE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger("eoc.router_process")

INBOUND_TOPIC = "eoc-events"
GROUP_ID      = "eoc-router"


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

    router = EOCRouter(config=config)
    log.info("[RouterProcess] Initialized | broker=%s | inbound=%s", broker, INBOUND_TOPIC)

    # K9EventBus ABB — inbound consumer
    inbound_bus = K9EventBus(
        broker_url=broker,
        topic=INBOUND_TOPIC,
        group_id=GROUP_ID,
    )

    async def handle(payload: dict) -> None:
        event_type = payload.get("event_type", "")
        corr       = payload.get("correlation_id", "")
        log.info("[RouterProcess] Received event_type=%s corr=%s", event_type, corr)
        try:
            routed = router.route(event_type, payload)
            if routed:
                topic = _ROUTING_TABLE.get(event_type.lower().strip(), "?")
                bus   = router._buses.get(event_type.lower().strip())
                if bus and bus._producer:
                    bus._producer.flush()
                print(
                    f"\n  ▶ ROUTER  PUBLISH  event_type='{event_type}'  →  topic='{topic}'  corr={corr}\n",
                    flush=True,
                )
            else:
                log.warning("[RouterProcess] No route for event_type=%r", event_type)
        except Exception as exc:
            log.error("[RouterProcess] Routing failed: %s", exc, exc_info=True)

    log.info("[RouterProcess] Starting K9EventBus async consumer …")
    try:
        await inbound_bus.subscribe_async(handle)
    finally:
        router.close()
        log.info("[RouterProcess] Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[RouterProcess] Shutdown requested.")
    except Exception as exc:
        log.error("[RouterProcess] Fatal: %s", exc, exc_info=True)
