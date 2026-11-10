# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Keeps CAPABILITIES.md honest against the code.

The index is what a developer (or an LLM working in this repo) reads before
designing anything, so an ABB missing from it is a feature that gets rebuilt
by someone who didn't know it existed. Two properties:

- every ``Base*`` class defined in ``k9_aif_abb`` appears in the index;
- every class name the index mentions is defined in ``k9_aif_abb``.
"""

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
INDEX = PACKAGE / "CAPABILITIES.md"  # symlink to the repo-root copy; ships in the wheel

# A backticked CamelCase identifier: `K9RulesAdapter`, `BaseAgent`.
_CLASS_REF = re.compile(r"`([A-Z][A-Za-z0-9]+)`")


def _defined_classes():
    names = set()
    for path in PACKAGE.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    return names


def _index_text():
    if not INDEX.exists():
        pytest.skip("CAPABILITIES.md not found next to the package")
    return INDEX.read_text(encoding="utf-8")


def test_every_abb_is_in_the_index():
    referenced = set(_CLASS_REF.findall(_index_text()))
    abbs = {n for n in _defined_classes() if n.startswith("Base")}
    missing = sorted(abbs - referenced)
    assert not missing, f"Add these ABBs to CAPABILITIES.md: {missing}"


def test_every_class_in_the_index_exists():
    referenced = set(_CLASS_REF.findall(_index_text()))
    unknown = sorted(referenced - _defined_classes())
    assert not unknown, f"CAPABILITIES.md names classes that don't exist: {unknown}"
