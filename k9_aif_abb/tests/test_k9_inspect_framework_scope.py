# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""The inspector recognises the K9-AIF framework itself and does not grade it as a solution."""

from pathlib import Path

from k9_aif_abb.k9_inspect import K9Inspector

ABB = Path(__file__).resolve().parents[1]          # k9_aif_abb/
REPO = ABB.parent                                   # the framework repository


def test_framework_package_is_not_graded():
    r = K9Inspector().inspect(ABB)
    assert r.scope == "framework"
    assert r.verdict == "K9-AIF FRAMEWORK"
    assert r.score is None and r.rules == [] and r.findings == []
    assert "framework itself" in r.note and "examples/<App>" in r.note
    assert r.to_dict()["scope"] == "framework"
    assert "rules not applied" in r.to_markdown()


def test_framework_repository_root_is_not_graded():
    assert K9Inspector().inspect(REPO).scope == "framework"


def test_an_example_solution_is_still_inspected():
    r = K9Inspector().inspect(REPO / "examples" / "acme_support_center")
    assert r.scope == "solution"
    assert r.rules and r.verdict in ("COMPLIANT", "COMPLIANT WITH WARNINGS", "NON-COMPLIANT")
