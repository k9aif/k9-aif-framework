# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Model integrity (1.18.6): the weights a model alias runs on are the weights the architect approved.

A local model server loads a model by tag (``granite3.3:8b``), and a tag is a moving name: a
``ollama pull``, a mirror, or someone with access to the host can put different weights behind
the same tag, and every agent keeps calling it. Pin the content digest in the model's config and
the provider checks it before it sends a prompt:

.. code-block:: yaml

    inference:
      llm_factory:
        models:
          reasoning:
            model: granite3.3:8b
            digest: sha256:fd3c2b5ec1...     # `ollama list` / GET /api/tags
            digest_recheck_seconds: 300      # optional, default 300

A different or missing digest raises ``ModelIntegrityError`` (a ``PermissionError``, the
framework's block signal): the call is refused, not retried, and a ``ModelIntegrity`` trace
event records it. Opt-in per model; a model without ``digest`` behaves as before.

Limits: applies to models served by Ollama (the digest is the server's manifest digest; hosted
APIs expose none, and configuring ``digest`` for them is a configuration error). It proves the
server holds the approved weights under that tag, not where those weights came from: approve a
digest only after checking the model's source.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

from k9_aif_abb.k9_utils.trace_events import emit_trace_event

DEFAULT_RECHECK_SECONDS = 300


class ModelIntegrityError(PermissionError):
    """The served model is not the pinned one."""


def normalize_digest(digest: Optional[str]) -> str:
    d = str(digest or "").strip().lower()
    return d.split(":", 1)[1] if d.startswith("sha256:") else d


def served_digest(tags: Dict[str, Any], model: str) -> Optional[str]:
    """The digest the server reports for ``model`` in a GET /api/tags answer (``name`` or ``model``;
    a bare name matches ``:latest``)."""
    wanted = {model, model if ":" in model else f"{model}:latest"}
    for entry in (tags or {}).get("models") or []:
        if entry.get("name") in wanted or entry.get("model") in wanted:
            return normalize_digest(entry.get("digest"))
    return None


def check_digest(model: str, expected: str, tags: Dict[str, Any]) -> None:
    """Raise ModelIntegrityError unless the server serves ``model`` with digest ``expected``."""
    want = normalize_digest(expected)
    got = served_digest(tags, model)
    ok = bool(got) and got == want
    emit_trace_event({"type": "ModelIntegrity", "model": model, "allowed": ok,
                      "expected": want[:12], "served": (got or "")[:12]})
    if not got:
        raise ModelIntegrityError(f"model {model!r} refused: the server does not list it, so its digest "
                                  f"cannot be checked against the pinned sha256:{want[:12]}")
    if not ok:
        raise ModelIntegrityError(f"model {model!r} refused: the server holds sha256:{got[:12]}, the "
                                  f"configuration pins sha256:{want[:12]} (the weights behind this tag "
                                  f"changed)")


class DigestPin:
    """Per-provider-instance state: when the pinned model was last verified."""

    def __init__(self, model: str, digest: Optional[str], recheck_seconds: Optional[float] = None):
        self.model = model
        self.digest = digest
        self.recheck = float(recheck_seconds if recheck_seconds is not None else DEFAULT_RECHECK_SECONDS)
        self._verified_at: Optional[float] = None

    @property
    def enabled(self) -> bool:
        return bool(self.digest)

    def due(self) -> bool:
        return self.enabled and (self._verified_at is None or time.monotonic() - self._verified_at >= self.recheck)

    def verify(self, tags: Dict[str, Any]) -> None:
        self._verified_at = None
        check_digest(self.model, self.digest, tags)
        self._verified_at = time.monotonic()
