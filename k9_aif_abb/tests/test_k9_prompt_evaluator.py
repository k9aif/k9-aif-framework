# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Tests for K9PromptEvaluator and BasePromptEvaluator ABB.

llm_invoke is patched at the module level — no LLM or network required.
All tests are fully offline.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from k9_aif_abb.k9_agents.evaluation.k9_prompt_evaluator import K9PromptEvaluator
from k9_aif_abb.k9_agents.evaluation.models.evaluation import (
    ComparisonResult,
    DimensionScore,
    EvaluationResult,
    PromptTestCase,
    SuiteResult,
    score_to_grade,
)
from k9_aif_abb.k9_core.evaluation.base_prompt_evaluator import BasePromptEvaluator


# ── Helpers ────────────────────────────────────────────────────────────────────

def _judge_response(
    correctness=85, completeness=80, format_compliance=90,
    clarity=88, relevance=92, overall="Good response."
):
    return json.dumps({
        "correctness":       {"score": correctness,       "rationale": "Correct."},
        "completeness":      {"score": completeness,      "rationale": "Complete."},
        "format_compliance": {"score": format_compliance, "rationale": "Follows format."},
        "clarity":           {"score": clarity,           "rationale": "Clear."},
        "relevance":         {"score": relevance,         "rationale": "Relevant."},
        "overall_rationale": overall,
    })


def _invoke_response(text="This is the model output."):
    return text


def _make(config=None):
    return K9PromptEvaluator(config=config or {})


def _patch_llm(judge_out: str, invoke_out: str = "Model output."):
    """Patch llm_invoke: judge calls (operation=evaluate) get judge_out; generation gets invoke_out."""
    def side_effect(cfg, req):
        mock = MagicMock()
        op = (req.metadata or {}).get("operation")
        mock.output = judge_out if op == "evaluate" else invoke_out
        return mock

    return patch(
        "k9_aif_abb.k9_agents.evaluation.k9_prompt_evaluator.llm_invoke",
        side_effect=side_effect,
    )


def _patch_judge_only(judge_out: str):
    """Patch llm_invoke for evaluate() calls where actual_output is already provided."""
    mock_resp = MagicMock()
    mock_resp.output = judge_out
    return patch(
        "k9_aif_abb.k9_agents.evaluation.k9_prompt_evaluator.llm_invoke",
        return_value=mock_resp,
    )


# ── score_to_grade ─────────────────────────────────────────────────────────────

def test_score_to_grade_boundaries():
    assert score_to_grade(100) == "A"
    assert score_to_grade(90)  == "A"
    assert score_to_grade(89)  == "B"
    assert score_to_grade(80)  == "B"
    assert score_to_grade(79)  == "C"
    assert score_to_grade(70)  == "C"
    assert score_to_grade(69)  == "D"
    assert score_to_grade(60)  == "D"
    assert score_to_grade(59)  == "F"
    assert score_to_grade(0)   == "F"


# ── BasePromptEvaluator ABB ────────────────────────────────────────────────────

def test_base_prompt_evaluator_is_abstract():
    """Cannot instantiate without implementing all abstract methods."""
    with pytest.raises(TypeError):
        BasePromptEvaluator()


# ── evaluate() ────────────────────────────────────────────────────────────────

def test_evaluate_returns_evaluation_result():
    evaluator = _make()
    judge_out = _judge_response()
    with _patch_judge_only(judge_out):
        result = evaluator.evaluate(
            prompt="Answer clearly.",
            input_data={"question": "What is K9-AIF?"},
            actual_output="K9-AIF is an architecture-first framework.",
            expected="A clear description of K9-AIF.",
        )
    assert isinstance(result, EvaluationResult)
    assert result.verdict in ("PASS", "FAIL")
    assert 0 <= result.score <= 100
    assert result.grade in ("A", "B", "C", "D", "F")
    assert len(result.dimensions) == 5


def test_evaluate_composite_score_weighted():
    """Composite = correctness*0.35 + completeness*0.25 + format*0.15 + clarity*0.15 + relevance*0.10"""
    evaluator = _make()
    judge_out = _judge_response(
        correctness=100, completeness=100, format_compliance=100,
        clarity=100, relevance=100,
    )
    with _patch_judge_only(judge_out):
        result = evaluator.evaluate("p", {}, "out", "expected")
    assert result.score == 100.0
    assert result.grade == "A"


def test_evaluate_pass_verdict_above_threshold():
    evaluator = _make({"pass_threshold": 70})
    judge_out = _judge_response(
        correctness=80, completeness=80, format_compliance=80,
        clarity=80, relevance=80,
    )
    with _patch_judge_only(judge_out):
        result = evaluator.evaluate("p", {}, "out", "expected")
    assert result.verdict == "PASS"


def test_evaluate_fail_verdict_below_threshold():
    evaluator = _make({"pass_threshold": 70})
    judge_out = _judge_response(
        correctness=40, completeness=40, format_compliance=40,
        clarity=40, relevance=40,
    )
    with _patch_judge_only(judge_out):
        result = evaluator.evaluate("p", {}, "out", "expected")
    assert result.verdict == "FAIL"


def test_evaluate_custom_pass_threshold():
    evaluator = _make({"pass_threshold": 90})
    judge_out = _judge_response(
        correctness=80, completeness=80, format_compliance=80,
        clarity=80, relevance=80,
    )
    with _patch_judge_only(judge_out):
        result = evaluator.evaluate("p", {}, "out", "expected")
    assert result.verdict == "FAIL"


def test_evaluate_dimension_names():
    evaluator = _make()
    with _patch_judge_only(_judge_response()):
        result = evaluator.evaluate("p", {}, "out", "expected")
    names = {d.name for d in result.dimensions}
    assert names == {"correctness", "completeness", "format_compliance", "clarity", "relevance"}


def test_evaluate_malformed_json_falls_back_gracefully():
    evaluator = _make()
    with _patch_judge_only("not valid json at all"):
        result = evaluator.evaluate("p", {}, "out", "expected")
    assert isinstance(result, EvaluationResult)
    assert result.score == 50.0 * (0.35 + 0.25 + 0.15 + 0.15 + 0.10)


# ── compare() ─────────────────────────────────────────────────────────────────

def test_compare_returns_comparison_result():
    evaluator = _make()
    tc = PromptTestCase(input_data={"q": "test"}, expected="expected", description="t1")

    with _patch_llm(_judge_response(correctness=90, completeness=90, format_compliance=90,
                                    clarity=90, relevance=90)):
        result = evaluator.compare("prompt_a", "prompt_b", [tc])

    assert isinstance(result, ComparisonResult)
    assert result.winner in ("prompt_a", "prompt_b", "tie")
    assert len(result.results_a) == 1
    assert len(result.results_b) == 1


def test_compare_tie_when_scores_close():
    evaluator = _make()
    tc = PromptTestCase(input_data={"q": "test"}, expected="expected")

    with _patch_llm(_judge_response()):
        result = evaluator.compare("prompt_a", "prompt_b", [tc])

    assert result.winner == "tie"


# ── run_suite() ───────────────────────────────────────────────────────────────

def test_run_suite_returns_suite_result():
    evaluator = _make()
    cases = [
        PromptTestCase(input_data={"q": f"q{i}"}, expected="expected", description=f"case {i}")
        for i in range(3)
    ]
    with _patch_llm(_judge_response()):
        result = evaluator.run_suite("my prompt", cases)

    assert isinstance(result, SuiteResult)
    assert result.total == 3
    assert result.passed + result.failed == result.total
    assert 0.0 <= result.pass_rate <= 1.0


def test_run_suite_all_pass():
    evaluator = _make({"pass_threshold": 70})
    cases = [PromptTestCase(input_data={"q": "q"}, expected="e") for _ in range(2)]
    with _patch_llm(_judge_response(correctness=90, completeness=90,
                                    format_compliance=90, clarity=90, relevance=90)):
        result = evaluator.run_suite("p", cases)

    assert result.passed == 2
    assert result.failed == 0
    assert result.pass_rate == 1.0


def test_run_suite_all_fail():
    evaluator = _make({"pass_threshold": 70})
    cases = [PromptTestCase(input_data={"q": "q"}, expected="e") for _ in range(2)]
    with _patch_llm(_judge_response(correctness=30, completeness=30,
                                    format_compliance=30, clarity=30, relevance=30)):
        result = evaluator.run_suite("p", cases)

    assert result.failed == 2
    assert result.passed == 0
    assert result.pass_rate == 0.0


def test_run_suite_average_score_and_grade():
    evaluator = _make()
    cases = [PromptTestCase(input_data={"q": "q"}, expected="e")]
    with _patch_llm(_judge_response(correctness=100, completeness=100,
                                    format_compliance=100, clarity=100, relevance=100)):
        result = evaluator.run_suite("p", cases)

    assert result.average_score == 100.0
    assert result.overall_grade == "A"


# ── EvaluationResult __str__ ──────────────────────────────────────────────────

def test_evaluation_result_str():
    result = EvaluationResult(
        score=85.0, grade="B", verdict="PASS",
        dimensions=[DimensionScore("correctness", 85.0, "Good")],
        rationale="Solid response.",
        actual_output="output",
        prompt="prompt",
    )
    text = str(result)
    assert "85.0" in text
    assert "PASS" in text
    assert "correctness" in text
