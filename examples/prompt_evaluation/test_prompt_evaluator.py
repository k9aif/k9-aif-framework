#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Prompt Evaluation Test Client
==============================
Demonstrates three evaluation modes:

  1. evaluate()   — score one (prompt, input, actual_output) triple
  2. compare()    — A/B test two prompt variants across test cases
  3. run_suite()  — batch-evaluate a prompt against a full suite

Run:
    cd k9-aif-framework
    source .venv/bin/activate
    python examples/prompt_evaluation/test_prompt_evaluator.py
"""

import sys
import os

# Bootstrap k9_aif_abb onto sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.evaluation_factory import EvaluationFactory
from k9_aif_abb.k9_agents.evaluation.models.evaluation import PromptTestCase

# ---------------------------------------------------------------------------
# Config — load_yaml resolves ${VAR:-default} and loads .env automatically
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
config = load_yaml(CONFIG_PATH)

LLMFactory.bootstrap(config)
evaluator = EvaluationFactory.create(config)

# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

PROMPT_GOOD = (
    "You are a helpful customer support agent. "
    "Answer the customer's question clearly and concisely. "
    "If you do not know the answer, say so honestly. "
    "Format your response as: Answer: <response>"
)

PROMPT_VAGUE = (
    "Answer the question."
)

TEST_CASES = [
    PromptTestCase(
        input_data={"question": "What is your return policy?"},
        expected=(
            "The response should state the return policy clearly, "
            "be polite, and follow the 'Answer: <response>' format."
        ),
        description="Return policy question",
    ),
    PromptTestCase(
        input_data={"question": "How do I reset my password?"},
        expected=(
            "The response should provide clear steps for password reset, "
            "remain helpful in tone, and follow the 'Answer: <response>' format."
        ),
        description="Password reset question",
    ),
    PromptTestCase(
        input_data={"question": "Can I change my order after it has shipped?"},
        expected=(
            "The response should acknowledge limitations around post-shipment changes, "
            "suggest alternatives if any, and follow the 'Answer: <response>' format."
        ),
        description="Post-shipment order change",
    ),
]

# ---------------------------------------------------------------------------
# 1. Single evaluate()
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("MODE 1: Single evaluate()")
print("=" * 60)

actual = evaluator._invoke_prompt(PROMPT_GOOD, TEST_CASES[0].input_data)
print(f"\nActual output:\n  {actual}\n")

result = evaluator.evaluate(
    prompt=PROMPT_GOOD,
    input_data=TEST_CASES[0].input_data,
    actual_output=actual,
    expected=TEST_CASES[0].expected,
    test_case_description=TEST_CASES[0].description,
)
print(result)

# ---------------------------------------------------------------------------
# 2. A/B compare()
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("MODE 2: A/B compare() — good prompt vs vague prompt")
print("=" * 60)

comparison = evaluator.compare(
    prompt_a=PROMPT_GOOD,
    prompt_b=PROMPT_VAGUE,
    test_cases=TEST_CASES,
)
print(f"\n{comparison}")

print("\nPer-case breakdown:")
for i, (ra, rb) in enumerate(zip(comparison.results_a, comparison.results_b)):
    tc = TEST_CASES[i]
    print(
        f"  [{tc.description}]  "
        f"A: {ra.score:.1f} {ra.grade} {ra.verdict}  |  "
        f"B: {rb.score:.1f} {rb.grade} {rb.verdict}"
    )

# ---------------------------------------------------------------------------
# 3. Suite run_suite()
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("MODE 3: run_suite() — full test suite on good prompt")
print("=" * 60)

suite = evaluator.run_suite(prompt=PROMPT_GOOD, test_cases=TEST_CASES)
print(f"\n{suite}")

print("\nPer-case results:")
for r in suite.results:
    print(
        f"  [{r.test_case_description}]  "
        f"Score: {r.score:.1f}  Grade: {r.grade}  Verdict: {r.verdict}"
    )
    for d in r.dimensions:
        print(f"    {d.name:<22} {d.score:5.1f}  {d.rationale}")

print("\nDone.")
