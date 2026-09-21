# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat auto-learning
#
# Detects when a user's next message is correcting something factually
# wrong the assistant just said, extracts the corrected fact as a clean
# standalone statement, and writes it straight into the shared knowledge
# base (k9x_knowledge_base, same collection knowledge_retriever.py reads
# from) so future turns -- this session or any other -- retrieve the
# corrected fact instead of repeating the mistake.
#
# No review queue: this instance is single-user/internal (home network
# only, no public exposure) -- see config.yaml's correction_learning
# section for why that assumption is load-bearing here and would need
# revisiting before any public/multi-tenant deployment.
#
# Same LLM-as-judge shape as k9_prompt_evaluator.py (structured JSON judge
# call), but this is detection + extraction, not scoring -- a different
# enough task that it isn't a BasePromptEvaluator implementation.

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke

log = logging.getLogger("k9chat.correction_learner")

_JUDGE_SYSTEM_PROMPT = (
    "You detect when a user is correcting a factual claim the assistant "
    "just made. You respond with only valid JSON -- no prose, no markdown "
    "fences."
)

_JUDGE_PROMPT_TEMPLATE = """\
## Assistant's prior reply
{prior_reply}

## User's next message
{new_message}

Is the user's message correcting, refuting, or fixing something factually
wrong in the assistant's prior reply? This means the user is asserting a
fact that contradicts what the assistant said. It does NOT include: asking
a follow-up question, asking for something different, expressing a
preference or opinion, or general disagreement without a specific
corrected fact.

If yes, extract the corrected fact as one clean, standalone, self-contained
statement someone could read later with zero other context and understand
correctly on its own (e.g. "K9X Studio is installed via `pip install k9x`,
not a separate SDK download.").

Return this JSON object and nothing else:
{{
  "is_correction": <true|false>,
  "corrected_fact": "<standalone corrected statement, or empty string if is_correction is false>"
}}
"""


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    log.warning("[CorrectionLearner] could not parse judge JSON from response")
    return {}


def detect_correction(
    config: Dict[str, Any], prior_reply: Optional[str], new_message: str
) -> Optional[str]:
    """Returns the extracted corrected-fact statement, or None if the new
    message isn't a correction or the judge call itself fails -- fails
    closed (never stores anything on an error rather than guessing).

    Does NOT check correction_learning.enabled itself -- the caller (chat.py's
    learn_from_correction(), gated by the runtime-toggleable
    is_correction_learning_enabled()) is the single source of truth for
    that, so a runtime toggle can't be silently overridden by this
    function re-reading the static config.yaml value."""
    if not prior_reply or not new_message:
        return None

    cl_cfg = config.get("correction_learning", {})
    judge_model = cl_cfg.get("judge_model", "reasoning")
    req = InferenceRequest(
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        prompt=_JUDGE_PROMPT_TEMPLATE.format(
            prior_reply=prior_reply, new_message=new_message
        ),
        task_type=judge_model,
        metadata={"component": "CorrectionLearner", "operation": "detect"},
    )
    try:
        resp = llm_invoke(config, req)
    except Exception as exc:
        log.warning("[CorrectionLearner] detection call failed: %s", exc)
        return None

    data = _extract_json(resp.output)
    if data.get("is_correction") and data.get("corrected_fact"):
        return str(data["corrected_fact"]).strip()
    return None


def learn(
    config: Dict[str, Any],
    knowledge_retriever,
    prior_reply: Optional[str],
    new_message: str,
    session_id: str = "default",
) -> Optional[Dict[str, Any]]:
    """Detects + stores a correction in one call. Returns
    {"corrected_fact": ...} if something was learned, else None. Never
    raises -- a failure here must never break the surrounding chat
    request."""
    try:
        corrected_fact = detect_correction(config, prior_reply, new_message)
        if not corrected_fact:
            return None

        doc_id = f"user_correction_{uuid.uuid4().hex[:12]}"
        stored = knowledge_retriever.store_chunk(
            doc_id=doc_id,
            text=corrected_fact,
            metadata={
                "source": "user_correction",
                "session_id": session_id,
                "learned_at": time.time(),
            },
        )
        if not stored:
            log.warning("[CorrectionLearner] store_chunk returned falsy for %s", doc_id)
            return None

        log.info("[CorrectionLearner] learned: %s", corrected_fact)
        return {"corrected_fact": corrected_fact}
    except Exception as exc:
        log.warning("[CorrectionLearner] learn() failed: %s", exc)
        return None
