# SPDX-License-Identifier: Apache-2.0
"""
Tests for ProfanityGovernance — contract-conformance and behavior (G4 fix).

Verifies pre_process()/post_process() return the payload dict (the same
contract every other BaseGovernance implementation follows), and that a
BLOCKED verdict raises PermissionError rather than silently replacing the
payload with a {"status": ...} dict.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from k9_aif_abb.k9_governance.profanity_governance import ProfanityGovernance


def _make_governance(generate_return: str) -> ProfanityGovernance:
    with patch(
        "k9_aif_abb.k9_governance.profanity_governance.LLMFactory.get"
    ) as mock_get:
        mock_get.return_value = AsyncMock(generate=AsyncMock(return_value=generate_return))
        return ProfanityGovernance()


def test_pre_process_returns_payload_on_safe():
    gov = _make_governance("SAFE - no profanity detected")
    payload = {"text": "What is the status of claim C001?"}
    result = asyncio.run(gov.pre_process(payload))
    assert result == payload


def test_pre_process_raises_on_blocked():
    gov = _make_governance("BLOCKED - profanity detected")
    payload = {"text": "some offensive text"}
    with pytest.raises(PermissionError, match="blocked ingress"):
        asyncio.run(gov.pre_process(payload))


def test_post_process_returns_payload():
    gov = _make_governance("SAFE")
    payload = {"response": "Claim C001 approved for $4,200."}
    result = asyncio.run(gov.post_process(payload))
    assert result == payload
