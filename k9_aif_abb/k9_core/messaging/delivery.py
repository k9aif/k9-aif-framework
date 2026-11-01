# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""At-least-once delivery for the framework's Kafka consumers (1.23).

A consumer commits a message's offset only after the message is accounted for: its handler
returned, or it was dead-lettered to ``<topic>.dlq``. A handler failure is retried with backoff
(``attempts``, default 5); after the last attempt, or at once for a message that cannot be
decoded or resolved (retrying cannot help), the message goes to the dead-letter topic with the
reason. If the dead-letter publish fails too, :class:`DeliveryError` is raised and nothing is
committed, so the message is delivered again when the consumer restarts.

Before 1.23 ``K9EventBus.subscribe()`` / ``subscribe_async()`` and ``KafkaEventFabric`` committed
offsets on a timer and logged a failed handler, so an event whose handling failed (a HIL reply
while the state store was down) was skipped for good.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("k9aif.delivery")

DEFAULT_ATTEMPTS = 5
DEFAULT_BACKOFF_S = 1.0
MAX_BACKOFF_S = 30.0


class DeliveryError(RuntimeError):
    """A message could be neither handled nor dead-lettered; its offset is not committed."""


class PermanentMessageError(ValueError):
    """The message itself is unusable (cannot be decoded); it is dead-lettered without retries."""


def decode_json(raw: Any) -> Any:
    """Decode a message value; bytes that are not JSON raise :class:`PermanentMessageError`."""
    if not isinstance(raw, (bytes, bytearray)):
        return raw
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermanentMessageError(f"message is not JSON: {exc}") from exc


def dead_letter_event(topic: str, msg: Any, reason: str, attempts: int) -> Dict[str, Any]:
    raw = getattr(msg, "value", None)
    if isinstance(raw, (bytes, bytearray)):
        value: Any = raw.decode("utf-8", errors="replace")
    else:
        value = raw
    return {
        "original_topic": topic,
        "partition": getattr(msg, "partition", None),
        "offset": getattr(msg, "offset", None),
        "reason": reason[:2000],
        "attempts": attempts,
        "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
        "value": value,
    }


def _backoff(attempt: int, base: float) -> float:
    return min(base * (2 ** (attempt - 1)), MAX_BACKOFF_S)


def handle_with_retry(handle: Callable[[], Any], *, topic: str, msg: Any,
                      dead_letter: Callable[[str, Dict[str, Any]], None],
                      attempts: int = DEFAULT_ATTEMPTS, backoff_s: float = DEFAULT_BACKOFF_S,
                      permanent: tuple = (PermanentMessageError,),
                      sleep: Callable[[float], None] = time.sleep) -> str:
    """Run ``handle`` until it succeeds; dead-letter after ``attempts`` failures or at once for a
    ``permanent`` error. Returns "handled" or "dead_lettered"; the caller commits after either.
    Raises :class:`DeliveryError` when the dead-letter publish fails."""
    attempt = 0
    while True:
        attempt += 1
        try:
            handle()
            return "handled"
        except permanent as exc:
            reason = f"{type(exc).__name__}: {exc}"
            break
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if attempt >= attempts:
                break
            log.warning("[delivery] %s offset=%s attempt %d/%d failed (%s); retrying",
                        topic, getattr(msg, "offset", "?"), attempt, attempts, reason)
            sleep(_backoff(attempt, backoff_s))
    _dead_letter(dead_letter, topic, msg, reason, attempt)
    return "dead_lettered"


async def handle_with_retry_async(handle: Callable[[], Any], *, topic: str, msg: Any,
                                  dead_letter: Callable[[str, Dict[str, Any]], None],
                                  attempts: int = DEFAULT_ATTEMPTS, backoff_s: float = DEFAULT_BACKOFF_S,
                                  permanent: tuple = (PermanentMessageError,)) -> str:
    """Async form of :func:`handle_with_retry`; ``handle`` may return an awaitable."""
    attempt = 0
    while True:
        attempt += 1
        try:
            result = handle()
            if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                await result
            return "handled"
        except permanent as exc:
            reason = f"{type(exc).__name__}: {exc}"
            break
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if attempt >= attempts:
                break
            log.warning("[delivery] %s offset=%s attempt %d/%d failed (%s); retrying",
                        topic, getattr(msg, "offset", "?"), attempt, attempts, reason)
            await asyncio.sleep(_backoff(attempt, backoff_s))
    await asyncio.to_thread(_dead_letter, dead_letter, topic, msg, reason, attempt)
    return "dead_lettered"


def _dead_letter(dead_letter: Callable[[str, Dict[str, Any]], None], topic: str, msg: Any,
                 reason: str, attempts: int) -> None:
    dlq = f"{topic}.dlq"
    try:
        dead_letter(dlq, dead_letter_event(topic, msg, reason, attempts))
    except Exception as exc:
        log.error("[delivery] %s offset=%s could not be handled (%s) or dead-lettered to %s (%s); "
                  "not committed, it will be delivered again", topic, getattr(msg, "offset", "?"),
                  reason, dlq, exc)
        raise DeliveryError(f"{topic}: dead-letter publish to {dlq} failed: {exc}") from exc
    log.error("[delivery] %s offset=%s dead-lettered to %s after %d attempt(s): %s",
              topic, getattr(msg, "offset", "?"), dlq, attempts, reason)


def producer_dead_letter(producer: Optional[Any], timeout_s: float = 30.0) -> Callable[[str, Dict[str, Any]], None]:
    """A dead-letter sender over a kafka-python producer whose value serializer takes a dict.
    It waits for the broker to accept the event, so a failure is seen."""
    def send(dlq: str, event: Dict[str, Any]) -> None:
        if producer is None:
            raise DeliveryError("no producer for the dead-letter topic")
        producer.send(dlq, value=event).get(timeout=timeout_s)
    return send
