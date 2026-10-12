# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""PIIBoundaryCheck: literal PII values; US ZIP codes in an address context, so
claim, order and reference numbers are not read as personal data (1.16.1)."""

import pytest

from k9_aif_abb.k9_security.vulnerability.checks import PIIBoundaryCheck
from k9_aif_abb.k9_security.vulnerability.models.check_result import CheckStatus


@pytest.mark.parametrize("text", [
    "Springfield, IL 62704",
    "ZIP: 62704",
    "zip code 62704-1234",
    "Postal code 10001",
    "Contact: jordan.ellis@example.com",
    "SSN 123-45-6789",
    "Call (555) 123-4567",
])
def test_pii_values_are_flagged(text):
    assert PIIBoundaryCheck().check({"t": text}).status == CheckStatus.FLAG


@pytest.mark.parametrize("text", [
    "Claim number: CLM-2026-48377",
    "Policy HO-6612-0451, police report PD-26-121907",
    "Total claimed: $1,900; settlement 19000 pending",
    "Order 48213 shipped in 2026",
])
def test_reference_numbers_and_amounts_pass(text):
    assert PIIBoundaryCheck().check({"t": text}).status == CheckStatus.PASS


def test_block_mode():
    result = PIIBoundaryCheck({"block_on_match": True}).check({"t": "Springfield, IL 62704"})
    assert result.status == CheckStatus.BLOCK
    assert result.metadata["pii_type"] == "US ZIP code"
