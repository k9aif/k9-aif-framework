# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
BasePromptEvaluator — ABB contract for prompt evaluation.

Defines three evaluation operations:

  evaluate()   — score a single (prompt, input, actual_output) against expected
  compare()    — A/B test two prompt variants across a set of test cases
  run_suite()  — batch-evaluate one prompt across a full test suite

Implementations supply the judge mechanism (LLM-as-judge, rule engine, embedding
similarity, etc.).  The OOB SBB is K9PromptEvaluator, which uses llm_invoke()
as the judge.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.base_component import BaseComponent


class BasePromptEvaluator(BaseComponent, ABC):
    """ABB contract — all prompt evaluators must implement these three methods."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None):
        super().__init__(config=config, monitor=monitor)

    # ------------------------------------------------------------------
    @abstractmethod
    def evaluate(
        self,
        prompt: str,
        input_data: Dict[str, Any],
        actual_output: str,
        expected: str,
    ):
        """
        Score a single LLM response.

        Args:
            prompt:        The prompt that was sent to the LLM.
            input_data:    The input variables / context provided alongside the prompt.
            actual_output: The LLM's response to evaluate.
            expected:      The expected answer or evaluation criteria description.

        Returns:
            EvaluationResult with numeric score (0-100), letter grade, verdict,
            per-dimension scores, and rationale.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    @abstractmethod
    def compare(
        self,
        prompt_a: str,
        prompt_b: str,
        test_cases,
    ):
        """
        A/B compare two prompt variants across a list of PromptTestCase objects.

        Each test case is run against both prompts; scores are averaged.

        Returns:
            ComparisonResult identifying the winner, average scores, and per-prompt
            grade for the full test set.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    @abstractmethod
    def run_suite(
        self,
        prompt: str,
        test_cases,
    ):
        """
        Batch-evaluate one prompt across a list of PromptTestCase objects.

        Returns:
            SuiteResult with per-case EvaluationResults, aggregate score,
            overall grade, pass rate, and pass/fail counts.
        """
        raise NotImplementedError
