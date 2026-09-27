# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# README.md is the PyPI long_description, and PyPI does not resolve relative
# links or image paths (they 404 on pypi.org/project/k9-aif/). This test fails
# if the README gains one. Logic lives in scripts/check_readme_links.py, shared
# with the .claude hook and the --check-urls HTTP check.
#
# Runs only in a repository checkout: the installed wheel ships neither the
# README nor scripts/, so it skips there.

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_readme_links.py"
README = REPO / "README.md"

pytestmark = pytest.mark.skipif(
    not (SCRIPT.is_file() and README.is_file()),
    reason="not a repository checkout (README.md / scripts/ not present)",
)


def _checker():
    spec = importlib.util.spec_from_file_location("check_readme_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_has_no_relative_links():
    bad = _checker().relative_links(README.read_text(encoding="utf-8"))
    assert not bad, "relative links in README.md (they 404 on PyPI): " + ", ".join(
        f"line {line}: {url}" for line, url in bad
    )


@pytest.mark.parametrize("snippet", [
    "[guide](docs/developers/Developer-guide.md)",
    "![diagram](docs/diagrams/x.png)",
    '<img src="docs/diagrams/x.png">',
    '<a href="CLAUDE.md#hooks">hooks</a>',
    "[ref]: SKILLS.md",
    "[here](./examples/foo)",
    "[![d](https://raw.githubusercontent.com/k9aif/k9-aif-framework/main/x.png)](docs/diagrams/x.png)",
])
def test_checker_flags_relative_forms(snippet):
    assert _checker().relative_links(snippet), f"not flagged: {snippet}"


@pytest.mark.parametrize("snippet", [
    "[guide](https://github.com/k9aif/k9-aif-framework/blob/main/docs/x.md)",
    "![d](https://raw.githubusercontent.com/k9aif/k9-aif-framework/main/docs/x.png)",
    "[top](#table-of-contents)",
    "[mail](mailto:someone@example.com)",
])
def test_checker_allows_absolute_and_anchor_forms(snippet):
    assert not _checker().relative_links(snippet), f"wrongly flagged: {snippet}"
