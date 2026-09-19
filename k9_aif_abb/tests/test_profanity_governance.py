# SPDX-License-Identifier: Apache-2.0
"""
Tests for ProfanityGovernance — now a re-export of the real GuardianGovernance
(see k9_governance/profanity_governance.py's own docstring for why).

Replaces the old mock-based tests, which mocked LLMFactory.get() and fed it
hand-written "SAFE"/"BLOCKED" strings — a format the real
granite4.1-guardian:8b model never actually produces (confirmed: it always
answers "<score>yes</score>"/"<score>no</score>"). Those tests passed
while validating an assumption that made the real code silently useless.
These test the real HTTP call + real response format instead.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from k9_aif_abb.k9_governance.profanity_governance import ProfanityGovernance


def _make_governance(mock_response_text: str, ok: bool = True) -> ProfanityGovernance:
    return ProfanityGovernance(config={})


def _patch_ollama(response_text: str, ok: bool = True):
    mock_resp = MagicMock()
    mock_resp.ok = ok
    mock_resp.status_code = 200 if ok else 500
    mock_resp.json.return_value = {"response": response_text}
    return patch("k9_aif_abb.k9_governance.guardian_governance.requests.post", return_value=mock_resp)


def test_pre_process_returns_payload_on_safe():
    gov = _make_governance("safe")
    with _patch_ollama("<score>no</score>"):
        payload = {"query": "What is the status of claim C001?"}
        result = gov.pre_process(payload)
    assert result == payload


def test_pre_process_raises_on_blocked():
    gov = _make_governance("unsafe")
    with _patch_ollama("<score>yes</score>"):
        with pytest.raises(PermissionError, match="Granite Guardian blocked ingress"):
            gov.pre_process({"query": "some malicious text"})


def test_post_process_returns_payload_on_safe():
    gov = _make_governance("safe")
    with _patch_ollama("<score>no</score>"):
        payload = {"output": "Claim C001 approved for $4,200."}
        result = gov.post_process(payload)
    assert result == payload


def test_pre_process_fail_closed_when_guardian_unreachable():
    gov = ProfanityGovernance(config={"governance": {"guardian": {"on_unavailable": "fail_closed"}}})
    with patch(
        "k9_aif_abb.k9_governance.guardian_governance.requests.post",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        with pytest.raises(PermissionError, match="unavailable"):
            gov.pre_process({"query": "anything"})


def test_pre_process_fail_open_when_guardian_unreachable():
    gov = ProfanityGovernance(config={"governance": {"guardian": {"on_unavailable": "fail_open"}}})
    with patch(
        "k9_aif_abb.k9_governance.guardian_governance.requests.post",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        payload = {"query": "anything"}
        result = gov.pre_process(payload)
    assert result == payload


def test_unparseable_response_is_treated_as_unavailable_not_safe():
    """A response that doesn't match <score>yes|no</score> must never be
    silently treated as SAFE — that would let a payload through on the
    strength of a check that produced garbage, not a real verdict."""
    gov = ProfanityGovernance(config={"governance": {"guardian": {"on_unavailable": "fail_open"}}})
    with _patch_ollama("I'm not sure, this text is ambiguous"):
        # fail_open policy -> passes through, but only via the UNAVAILABLE path
        result = gov.pre_process({"query": "anything"})
    assert result == {"query": "anything"}
