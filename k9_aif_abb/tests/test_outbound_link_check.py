# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""OutboundLinkCheck: suspicious links in agent output (k9x_Shield egress)."""

import asyncio

import pytest

from k9_aif_abb.k9_security.vulnerability.checks import OutboundLinkCheck
from k9_aif_abb.k9_security.vulnerability.models.check_result import CheckStatus
from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance

CFG = {"allowed_domains": ["acmeinsurance.com", "paypal.com"]}


def _check(text, cfg=CFG):
    return OutboundLinkCheck(cfg).check({"output": text})


@pytest.mark.parametrize("text,kind", [
    ("Log in at https://paypa1.com/login to confirm", "lookalike"),
    ("Pay at https://acme1nsurance.com/pay", "lookalike"),
    ("Verify at https://paypal.com.account-verify.io/", "brand_in_subdomain"),
    ("Go to https://paypal.com@evil.io/login", "userinfo"),
    ("Settle now: http://185.23.4.9/pay", "ip_literal"),
    ("Visit https://xn--pypal-4ve.com", "punycode"),
])
def test_high_risk_links_block(text, kind):
    r = _check(text)
    assert r.status is CheckStatus.BLOCK
    assert r.metadata["findings"][0]["kind"] == kind


@pytest.mark.parametrize("text,kind", [
    ("Details: https://bit.ly/3xYz", "shortener"),
    ("See https://example.org/docs", "not_allowlisted"),
])
def test_medium_risk_links_flag(text, kind):
    r = _check(text)
    assert r.status is CheckStatus.FLAG and r.metadata["findings"][0]["kind"] == kind


def test_allowed_domains_and_subdomains_pass():
    r = _check("Your claim: https://portal.acmeinsurance.com/claims/42 and www.paypal.com.")
    assert r.status is CheckStatus.PASS


def test_no_links_passes_and_nested_payloads_are_scanned():
    assert _check("Your claim was approved.").status is CheckStatus.PASS
    r = OutboundLinkCheck(CFG).check({"result": {"messages": ["ok", {"text": "pay https://paypa1.com"}]}})
    assert r.status is CheckStatus.BLOCK


def test_without_allowlist_only_structural_tricks_are_reported():
    assert _check("see https://example.org", cfg={}).status is CheckStatus.PASS
    assert _check("see https://paypal.com@evil.io", cfg={}).status is CheckStatus.BLOCK
    assert _check("pay https://paypa1.com", cfg={"protected_brands": ["paypal"]}).status is CheckStatus.BLOCK


def test_block_kinds_and_ignore_domains_are_configurable():
    cfg = {**CFG, "block_kinds": ["shortener"], "ignore_domains": ["example.org"]}
    assert _check("https://bit.ly/x", cfg).status is CheckStatus.BLOCK
    assert _check("https://paypa1.com", cfg).status is CheckStatus.FLAG
    assert _check("https://docs.example.org/a", cfg).status is CheckStatus.PASS


def test_short_brands_do_not_cause_false_lookalikes():
    # "ibm" is too short to compare safely: "ibn.com" must not be called a lookalike.
    r = _check("https://ibn.com", cfg={"allowed_domains": ["ibm.com"]})
    assert r.metadata["findings"][0]["kind"] == "not_allowlisted"


def test_shield_blocks_on_egress_with_the_check_enabled():
    gov = ShieldGovernance(config={"security": {"shield": {
        "enabled": True, "ingress": {"checks": []}, "egress": {"checks": ["OutboundLinkCheck"]},
        "check_config": {"OutboundLinkCheck": CFG}}}})
    with pytest.raises(PermissionError, match="OutboundLinkCheck"):
        r = gov.post_process({"output": "Settle your debt now at https://paypa1.com/pay"}, {})
        if asyncio.iscoroutine(r):
            asyncio.run(r)
