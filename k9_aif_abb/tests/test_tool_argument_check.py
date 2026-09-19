# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9x_Shield
"""
Regression tests for ToolArgumentCheck's markdown-code-fence false positive.

Found live against the real AccountsPayableExpenseReimbursements scaffold
(2026-09-19): the old `` `[^`]+` `` "Subshell injection" pattern matched
ANY pair of backticks, including a triple-backtick markdown fence — LLM
output that wraps JSON/code in ```json ... ``` was flagged as a subshell
injection attempt, blocking a completely benign Anomaly Detection run.
Documented as a known open gap in k9_aif_abb/k9_security/CLAUDE.md before
being fixed here.
"""

from k9_aif_abb.k9_security.vulnerability import ToolArgumentCheck
from k9_aif_abb.k9_security.vulnerability.models.check_result import CheckStatus


def _check():
    return ToolArgumentCheck(config={})


def test_fenced_json_output_is_not_flagged():
    payload = {
        "query": (
            "Here is the analysis:\n"
            "```json\n"
            '{"anomaly": false, "confidence": 0.92}\n'
            "```\n"
            "No issues found."
        )
    }
    result = _check().check(payload)
    assert result.status == CheckStatus.PASS


def test_multiple_fenced_blocks_not_flagged():
    payload = {
        "query": (
            "Step 1:\n```python\nx = 1\n```\n"
            "Step 2:\n```python\ny = 2\n```\n"
            "Both steps complete."
        )
    }
    result = _check().check(payload)
    assert result.status == CheckStatus.PASS


def test_benign_inline_backtick_identifier_not_flagged():
    payload = {"query": "The field `invoice_id` must be a non-empty string."}
    result = _check().check(payload)
    assert result.status == CheckStatus.PASS


def test_real_dollar_paren_subshell_still_blocked():
    payload = {"command": "echo hi; $(rm -rf /tmp/x)"}
    result = _check().check(payload)
    assert result.status == CheckStatus.BLOCK
    assert "Subshell injection" in result.message


def test_real_backtick_command_still_blocked():
    payload = {"query": "run this: `rm -rf /data`"}
    result = _check().check(payload)
    assert result.status == CheckStatus.BLOCK
    assert "Subshell injection" in result.message


def test_semicolon_command_injection_still_blocked():
    payload = {"command": "; cat /etc/passwd"}
    result = _check().check(payload)
    assert result.status == CheckStatus.BLOCK
