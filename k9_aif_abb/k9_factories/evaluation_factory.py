# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
EvaluationFactory — config-driven factory for BasePromptEvaluator.

Config key: evaluation.provider
  "k9"  (default) → K9PromptEvaluator (LLM-as-judge)

Example config.yaml:
  evaluation:
    provider: k9
    pass_threshold: 70
    judge_model: reasoning
"""

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class EvaluationFactory:

    @staticmethod
    def create(config: Optional[Dict[str, Any]] = None):
        """Return a configured BasePromptEvaluator instance."""
        cfg = config or {}
        provider = cfg.get("evaluation", {}).get("provider", "k9").lower()

        if provider == "k9":
            from k9_aif_abb.k9_agents.evaluation.k9_prompt_evaluator import K9PromptEvaluator
            log.info("[EvaluationFactory] Creating K9PromptEvaluator")
            return K9PromptEvaluator(config=cfg)

        raise ValueError(
            f"[EvaluationFactory] Unknown evaluation provider: '{provider}'. "
            f"Supported: 'k9'"
        )
