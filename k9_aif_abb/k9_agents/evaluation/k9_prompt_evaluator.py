# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9PromptEvaluator — OOB concrete implementation of BasePromptEvaluator.

Uses llm_invoke() as the judge.  Scores five dimensions, computes a weighted
composite, assigns a letter grade, and emits a PASS/FAIL verdict.

Evaluation dimensions and weights
----------------------------------
  correctness        0.35   Does the output correctly answer the task?
  completeness       0.25   Does it cover all required aspects?
  format_compliance  0.15   Does it follow the requested format/structure?
  clarity            0.15   Is the output clear, coherent, and readable?
  relevance          0.10   Is the output focused and on-topic?

Config keys
-----------
  model              str    llm_invoke task_type alias  (default: "reasoning")
  pass_threshold     float  Minimum composite score for PASS verdict (default: 70.0)
  judge_model        str    Override model alias for the judge specifically

Grade scale: A 90+, B 80–89, C 70–79, D 60–69, F <60
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from k9_aif_abb.k9_core.evaluation.base_prompt_evaluator import BasePromptEvaluator
from k9_aif_abb.k9_agents.evaluation.models.evaluation import (
    ComparisonResult,
    DimensionScore,
    EvaluationResult,
    PromptTestCase,
    SuiteResult,
    score_to_grade,
)
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke

log = logging.getLogger(__name__)

_DIMENSION_WEIGHTS = {
    "correctness":       0.35,
    "completeness":      0.25,
    "format_compliance": 0.15,
    "clarity":           0.15,
    "relevance":         0.10,
}

_JUDGE_SYSTEM_PROMPT = (
    "You are an expert prompt evaluation judge. "
    "Your role is to assess whether an AI model's response effectively fulfils a given prompt. "
    "You evaluate objectively, dimension by dimension, and return only valid JSON — no prose, "
    "no markdown fences."
)

_JUDGE_PROMPT_TEMPLATE = """\
Evaluate the AI response below against each dimension.

## Original Prompt
{prompt}

## Input Provided to the Model
{input_data}

## Expected Output / Evaluation Criteria
{expected}

## Actual Model Output
{actual_output}

Score each dimension 0–100 (100 = perfect):

  correctness        — Does the output correctly answer the task or question?
  completeness       — Does it cover all required aspects of the expected output?
  format_compliance  — Does it follow any format or structure specified in the prompt?
  clarity            — Is the output clear, coherent, and free of confusion?
  relevance          — Is the output focused and on-topic, without irrelevant content?

Return this JSON object and nothing else:
{{
  "correctness":       {{"score": <0-100>, "rationale": "<one sentence>"}},
  "completeness":      {{"score": <0-100>, "rationale": "<one sentence>"}},
  "format_compliance": {{"score": <0-100>, "rationale": "<one sentence>"}},
  "clarity":           {{"score": <0-100>, "rationale": "<one sentence>"}},
  "relevance":         {{"score": <0-100>, "rationale": "<one sentence>"}},
  "overall_rationale": "<one sentence summary>"
}}
"""


class K9PromptEvaluator(BasePromptEvaluator):
    """OOB LLM-as-judge prompt evaluator."""

    layer = "K9PromptEvaluator"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None):
        super().__init__(config=config, monitor=monitor)
        self._pass_threshold = float((config or {}).get("pass_threshold", 70.0))
        self._judge_model = (config or {}).get("judge_model") or (config or {}).get("model", "reasoning")

    # ------------------------------------------------------------------
    # BasePromptEvaluator implementation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        prompt: str,
        input_data: Dict[str, Any],
        actual_output: str,
        expected: str,
        test_case_description: str = "",
    ) -> EvaluationResult:
        judge_prompt = _JUDGE_PROMPT_TEMPLATE.format(
            prompt=prompt,
            input_data=json.dumps(input_data, indent=2),
            expected=expected,
            actual_output=actual_output,
        )
        req = InferenceRequest(
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            prompt=judge_prompt,
            task_type=self._judge_model,
            metadata={"component": self.layer, "operation": "evaluate"},
        )
        resp = llm_invoke(self.config, req)
        return self._parse_judge_response(
            resp.output, prompt, actual_output, test_case_description
        )

    def compare(
        self,
        prompt_a: str,
        prompt_b: str,
        test_cases: List[PromptTestCase],
    ) -> ComparisonResult:
        results_a: List[EvaluationResult] = []
        results_b: List[EvaluationResult] = []

        for tc in test_cases:
            # Both prompts receive the same input; we evaluate against the same expected
            output_a = self._invoke_prompt(prompt_a, tc.input_data)
            output_b = self._invoke_prompt(prompt_b, tc.input_data)
            results_a.append(self.evaluate(prompt_a, tc.input_data, output_a, tc.expected, tc.description))
            results_b.append(self.evaluate(prompt_b, tc.input_data, output_b, tc.expected, tc.description))

        avg_a = sum(r.score for r in results_a) / len(results_a) if results_a else 0.0
        avg_b = sum(r.score for r in results_b) / len(results_b) if results_b else 0.0

        if avg_a > avg_b + 2:
            winner = "prompt_a"
        elif avg_b > avg_a + 2:
            winner = "prompt_b"
        else:
            winner = "tie"

        rationale = (
            f"Prompt A averaged {avg_a:.1f} ({score_to_grade(avg_a)}); "
            f"Prompt B averaged {avg_b:.1f} ({score_to_grade(avg_b)}) "
            f"across {len(test_cases)} test case(s)."
        )

        return ComparisonResult(
            winner=winner,
            score_a=round(avg_a, 1),
            score_b=round(avg_b, 1),
            grade_a=score_to_grade(avg_a),
            grade_b=score_to_grade(avg_b),
            rationale=rationale,
            results_a=results_a,
            results_b=results_b,
        )

    def run_suite(
        self,
        prompt: str,
        test_cases: List[PromptTestCase],
    ) -> SuiteResult:
        results: List[EvaluationResult] = []

        for tc in test_cases:
            actual = self._invoke_prompt(prompt, tc.input_data)
            result = self.evaluate(prompt, tc.input_data, actual, tc.expected, tc.description)
            results.append(result)
            log.info(
                "[%s] Suite case '%s': score=%.1f grade=%s verdict=%s",
                self.layer, tc.description or "unnamed", result.score, result.grade, result.verdict,
            )

        passed = sum(1 for r in results if r.verdict == "PASS")
        failed = len(results) - passed
        avg = sum(r.score for r in results) / len(results) if results else 0.0
        pass_rate = passed / len(results) if results else 0.0

        return SuiteResult(
            total=len(results),
            passed=passed,
            failed=failed,
            average_score=round(avg, 1),
            overall_grade=score_to_grade(avg),
            pass_rate=round(pass_rate, 3),
            results=results,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invoke_prompt(self, prompt: str, input_data: Dict[str, Any]) -> str:
        req = InferenceRequest(
            prompt=prompt + "\n\nInput:\n" + json.dumps(input_data, indent=2),
            task_type=self.config.get("model", "general"),
            metadata={"component": self.layer, "operation": "invoke"},
        )
        resp = llm_invoke(self.config, req)
        return resp.output

    def _parse_judge_response(
        self,
        raw: str,
        prompt: str,
        actual_output: str,
        test_case_description: str,
    ) -> EvaluationResult:
        data = self._extract_json(raw)

        dimensions: List[DimensionScore] = []
        for name, weight in _DIMENSION_WEIGHTS.items():
            dim = data.get(name, {})
            score = float(dim.get("score", 50)) if isinstance(dim, dict) else 50.0
            rationale = dim.get("rationale", "") if isinstance(dim, dict) else ""
            dimensions.append(DimensionScore(name=name, score=score, rationale=rationale))

        composite = sum(
            d.score * _DIMENSION_WEIGHTS[d.name] for d in dimensions
        )
        composite = round(composite, 1)
        grade = score_to_grade(composite)
        verdict = "PASS" if composite >= self._pass_threshold else "FAIL"

        return EvaluationResult(
            score=composite,
            grade=grade,
            verdict=verdict,
            dimensions=dimensions,
            rationale=data.get("overall_rationale", ""),
            actual_output=actual_output,
            prompt=prompt,
            test_case_description=test_case_description,
        )

    @staticmethod
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
        log.warning("K9PromptEvaluator: could not parse judge JSON from response")
        return {}
