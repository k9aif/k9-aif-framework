# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Keeps k9_security/capabilities.yaml honest against the code.

The catalog is what K9X Sentinel compares new threats against; a control
missing from it would be reported as a gap, and a listed control that no
longer exists would hide a real one.
"""

import importlib
import re
from importlib import resources

import yaml

from k9_aif_abb.k9_governance.guardian_governance import RISK_DEFINITIONS
from k9_aif_abb.k9_security.vulnerability import checks

COVERAGE = {"full", "partial"}


def _catalog():
    text = (resources.files("k9_aif_abb.k9_security") / "capabilities.yaml").read_text()
    return yaml.safe_load(text)


def _resolve(path):
    module, _, attr = path.rpartition(".")
    return getattr(importlib.import_module(module), attr)


def test_catalog_ships_with_the_package_and_parses():
    cat = _catalog()
    assert cat["catalog_version"] == 1
    assert cat["capabilities"]


def test_framework_version_matches_pyproject():
    pyproject = resources.files("k9_aif_abb").joinpath("..", "pyproject.toml")
    try:
        text = pyproject.read_text()
    except (FileNotFoundError, NotADirectoryError):
        return  # installed wheel: no pyproject next to the package
    version = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert _catalog()["framework_version"] == version


def test_ids_are_unique():
    cat = _catalog()
    ids = [c["id"] for c in cat["capabilities"]] + [g["id"] for g in cat["known_gaps"]]
    assert len(ids) == len(set(ids))


def test_every_component_path_exists():
    for cap in _catalog()["capabilities"]:
        if "component" in cap:
            assert _resolve(cap["component"]), cap["id"]


def test_every_registered_shield_check_is_listed():
    listed = {c["component"].rsplit(".", 1)[1] for c in _catalog()["capabilities"] if c["kind"] == "shield_check"}
    assert listed == set(checks.__all__)


def test_every_guardian_risk_is_listed():
    listed = {c["risk"] for c in _catalog()["capabilities"] if c["kind"] == "guardian_risk"}
    assert listed == set(RISK_DEFINITIONS)


def test_coverage_uses_known_taxonomy_ids_and_levels():
    cat = _catalog()
    known = set(cat["taxonomies"]["owasp_llm_2025"]) | set(cat["taxonomies"]["owasp_agentic_2026"])
    for cap in cat["capabilities"]:
        assert cap["covers"], cap["id"]
        for tid, level in cap["covers"].items():
            assert tid in known, f"{cap['id']}: {tid}"
            assert level in COVERAGE, f"{cap['id']}: {level}"
    for gap in cat["known_gaps"]:
        assert set(gap["covers"]) <= known, gap["id"]
