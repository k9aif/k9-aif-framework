# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9ContextSynthesizerAgent: the squad coordinator's synthesizer (1.16).

A squad's agents run in sequence and, by default, each reads the full
accumulated context, so the prompt grows with every step. When a squad sets
``synthesis:`` (``auto`` or ``always``), BaseSquad asks this agent for a
digest of the upstream results and gives the next agent that digest instead
of every full output. The full outputs stay in the squad's results for audit.

It is an ordinary BaseAgent, so governance by construction screens its
digest like any agent output. A solution can replace it by naming its own
agent in ``synthesis.agent``.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke

SYSTEM_PROMPT = (
    "You are the coordinator of a team of agents. Condense the results the team has "
    "produced so far into a digest the next agent can work from. Keep every fact, "
    "number, identifier, decision, score, risk and open issue; drop repetition and "
    "narrative. Name the result key each point comes from, e.g. [criteria]. Write "
    "plain text, not JSON. Do not add anything the results do not say."
)


class K9ContextSynthesizerAgent(BaseAgent):
    """OOB synthesizer: ``execute({"results": {...}, "task": str})`` returns
    ``{"output": digest, "source_keys": [...]}``."""

    layer = "Squad Coordinator"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        results = payload.get("results") or {}
        task = payload.get("task") or ""
        body = json.dumps(results, default=str, ensure_ascii=False, indent=1)
        prompt = (
            (f"Team task: {task}\n\n" if task else "")
            + "Results so far, by result key:\n"
            + body
            + "\n\nWrite the digest."
        )
        max_tokens = (self.config.get("squad_synthesis") or {}).get("max_tokens")
        resp = llm_invoke(self.config, InferenceRequest(
            prompt=prompt, system_prompt=SYSTEM_PROMPT, task_type="summarization",
            max_tokens=max_tokens))
        return {"output": (resp.output or "").strip(), "source_keys": list(results)}
