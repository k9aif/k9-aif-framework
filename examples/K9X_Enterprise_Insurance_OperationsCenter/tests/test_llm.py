# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — tests/test_llm.py
#
# Standalone LLM connectivity and routing test.
# Runs a series of real inference calls through the full
# ModelRouterFactory → K9ModelRouter → LLMFactory → OllamaLLM chain.
#
# Usage:
#   cd /Users/ravinatarajan/ai/k9-aif-framework
#   python -m examples.K9X_Enterprise_Insurance_OperationsCenter.tests.test_llm

from __future__ import annotations

import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest

CONFIG_PATH = "examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml"

# Each test case: (label, task_type, prompt)
TEST_CASES = [
    (
        "General / Chat",
        "general",
        "In one sentence, what is insurance?",
    ),
    (
        "Reasoning / Adjudication",
        "adjudication",
        "A property claim for $45,000 was filed after a kitchen fire. "
        "Policy covers fire damage up to $100,000. Should this be approved? "
        "Reply: DECISION: <approve|deny|partial|escalate>  CONFIDENCE: <0-1>  RATIONALE: <one sentence>",
    ),
    (
        "Fraud Detection",
        "fraud",
        "Three claims filed within 30 days by the same claimant, all citing the same vendor. "
        "Amounts: $12k, $11.5k, $13k. "
        "Reply: RISK_SCORE: <0-1>  SIGNALS: <list>  RECOMMENDATION: <monitor|flag|block|escalate>",
    ),
    (
        "Guardian / Guardrails",
        "guardrails",
        "Check this content for PII and policy violations:\n"
        "Claimant SSN: 123-45-6789, email: john@example.com, claim amount $5000.\n"
        "Reply: PII_DETECTED: <yes|no>  VIOLATIONS: <list or none>  PASSED: <yes|no>",
    ),
    (
        "Extraction",
        "extraction",
        "Extract structured data from:\n"
        "'Invoice #INV-9921 dated 2024-03-15. Provider: Acme Repairs. "
        "Amount due: $3,250. Policy: POL-AUTO-441.'\n"
        "Return JSON with: invoice_number, date, provider, amount, policy_number.",
    ),
]


def run_test(router, label: str, task_type: str, prompt: str) -> bool:
    log.info("─" * 60)
    log.info("TEST: %s  (task_type=%s)", label, task_type)
    req = InferenceRequest(
        prompt=prompt,
        task_type=task_type,
        metadata={"agent": "test_llm", "test": label},
    )
    t0 = time.monotonic()
    try:
        resp = router.invoke(req)
    except Exception as exc:
        log.error("FAIL  %s — %s", label, exc)
        return False

    elapsed = int((time.monotonic() - t0) * 1000)

    if not resp.output or resp.output.startswith("[WARN]"):
        log.error("FAIL  %s — LLM returned: %s", label, resp.output)
        return False

    log.info("PASS  model=%-30s  latency=%dms", resp.model_alias, elapsed)
    log.info("      output (first 200 chars): %s", resp.output[:200].replace("\n", " "))
    return True


def main() -> int:
    log.info("=" * 60)
    log.info("K9X EOC — LLM routing test suite")
    log.info("=" * 60)

    config = load_yaml(CONFIG_PATH)

    log.info("Bootstrapping LLMFactory...")
    LLMFactory.bootstrap(config)

    log.info("Building ModelRouter...")
    router = ModelRouterFactory.get_router(config)
    log.info("Router class: %s", router.__class__.__name__)

    results = {}
    for label, task_type, prompt in TEST_CASES:
        results[label] = run_test(router, label, task_type, prompt)

    log.info("=" * 60)
    log.info("RESULTS")
    log.info("=" * 60)
    passed = 0
    for label, ok in results.items():
        status = "PASS ✓" if ok else "FAIL ✗"
        log.info("  %-30s  %s", label, status)
        if ok:
            passed += 1

    log.info("─" * 60)
    log.info("%d / %d tests passed", passed, len(TEST_CASES))

    return 0 if passed == len(TEST_CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
