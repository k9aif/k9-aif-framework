# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Evaluation data models for K9PromptEvaluator.

Grade scale:
    A  90–100   Excellent
    B  80–89    Good
    C  70–79    Acceptable
    D  60–69    Needs improvement
    F  0–59     Failing

Verdict:
    PASS   score >= pass_threshold (default 70)
    FAIL   score <  pass_threshold
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


def score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


# ---------------------------------------------------------------------------

@dataclass
class PromptTestCase:
    """One test case: the input fed to the LLM and the expected output / criteria."""
    input_data: Dict[str, Any]
    expected: str
    description: str = ""


@dataclass
class DimensionScore:
    """Score on a single evaluation dimension."""
    name: str
    score: float        # 0–100
    rationale: str


@dataclass
class EvaluationResult:
    """Result of evaluating one (prompt, input, actual_output) triple."""
    score: float                          # 0–100 composite
    grade: str                            # A/B/C/D/F
    verdict: str                          # PASS / FAIL
    dimensions: List[DimensionScore]
    rationale: str                        # one-sentence overall summary
    actual_output: str
    prompt: str
    test_case_description: str = ""

    def __str__(self) -> str:
        dim_lines = "\n".join(
            f"  {d.name:<22} {d.score:5.1f}  {d.rationale}"
            for d in self.dimensions
        )
        return (
            f"Score: {self.score:.1f}  Grade: {self.grade}  Verdict: {self.verdict}\n"
            f"{dim_lines}\n"
            f"Summary: {self.rationale}"
        )


@dataclass
class ComparisonResult:
    """Result of an A/B comparison between two prompt variants."""
    winner: str                           # "prompt_a" | "prompt_b" | "tie"
    score_a: float
    score_b: float
    grade_a: str
    grade_b: str
    rationale: str
    results_a: List[EvaluationResult] = field(default_factory=list)
    results_b: List[EvaluationResult] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Winner: {self.winner.upper()}\n"
            f"Prompt A: {self.score_a:.1f} ({self.grade_a})  "
            f"Prompt B: {self.score_b:.1f} ({self.grade_b})\n"
            f"{self.rationale}"
        )


@dataclass
class SuiteResult:
    """Aggregate result of running a prompt across a full test suite."""
    total: int
    passed: int
    failed: int
    average_score: float
    overall_grade: str
    pass_rate: float                      # 0.0–1.0
    results: List[EvaluationResult] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Suite: {self.passed}/{self.total} passed ({self.pass_rate*100:.0f}%)  "
            f"Avg score: {self.average_score:.1f}  Grade: {self.overall_grade}"
        )
