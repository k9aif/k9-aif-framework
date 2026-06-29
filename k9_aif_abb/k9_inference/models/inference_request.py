# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
InferenceRequest — the input contract for all LLM invocations.

``prompt`` carries the user-level content (the task, the document, the question).
``system_prompt`` carries system-level instructions (agent role, persona, constraints).

Keeping them separate allows LLM adapters to use provider-native system channels
(Ollama ``system``, Claude ``system`` parameter, OpenAI ``system`` role) and enables
prompt caching — the system portion is stable across calls and cacheable independently.

Agents populate both from their YAML config::

    req = InferenceRequest(
        system_prompt=f"Role: {self.config.get('role')}\\nGoal: {self.config.get('goal')}",
        prompt=f"Analyze: {payload.get('source_markdown')}",
        task_type="reasoning",
    )
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any


class InferenceRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    task_type: Optional[str] = None

    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

    sensitivity: Optional[str] = None

    # Routing hints — used by K9ModelRouter scoring.
    # When omitted (None) the router falls back to capability-only matching,
    # preserving backwards compatibility with all existing callers.
    latency_budget: Optional[str] = None   # "realtime" | "interactive" | "batch"
    cost_profile:   Optional[str] = None   # "minimal" | "standard" | "premium"

    metadata: Optional[Dict[str, Any]] = None