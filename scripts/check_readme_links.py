#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Guard: README.md must contain only absolute links and image URLs.

README.md is also the PyPI long_description, and PyPI does not resolve
relative paths: on https://pypi.org/project/k9-aif/ a link such as
`docs/x.md` becomes pypi.org/project/k9-aif/docs/x.md and returns 404.
Use absolute URLs instead:

  pages / files  https://github.com/k9aif/k9-aif-framework/blob/main/<path>
  directories    https://github.com/k9aif/k9-aif-framework/tree/main/<path>
  images         https://raw.githubusercontent.com/k9aif/k9-aif-framework/main/<path>

In-page anchors (#section) and mailto: links are fine.

Usage:
  python scripts/check_readme_links.py              # fail on relative links (offline)
  python scripts/check_readme_links.py --check-urls # also require HTTP 200 for every URL
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path
from typing import List, Tuple

README = Path(__file__).resolve().parents[1] / "README.md"

# Markdown links/images: [text](url "title") and ![alt](url)
_MD_LINK = re.compile(r'!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
# Outer link of a linked image: [![alt](img)](url) -- _MD_LINK alone only
# sees the inner image, because the outer link text contains brackets.
_MD_LINKED_IMAGE = re.compile(r'\[!\[[^\]]*\]\([^)]*\)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
# HTML attributes: <a href="..."> and <img src="...">
_HTML_ATTR = re.compile(r'\b(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
# Reference-style definitions: [label]: url
_REF_DEF = re.compile(r'^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)', re.M)
_ALLOWED = re.compile(r'^(https?://|mailto:|#)', re.I)


def extract_links(text: str) -> List[Tuple[int, str]]:
    """Every link/image target in `text`, as (line number, url), in file order."""
    found = []
    for pattern in (_MD_LINK, _MD_LINKED_IMAGE, _HTML_ATTR, _REF_DEF):
        for m in pattern.finditer(text):
            found.append((text.count("\n", 0, m.start()) + 1, m.group(1)))
    return sorted(found)


def relative_links(text: str) -> List[Tuple[int, str]]:
    """Targets that are neither absolute URLs, mailto:, nor in-page anchors."""
    return [(line, url) for line, url in extract_links(text) if not _ALLOWED.match(url)]


def check_urls(urls: List[str], timeout: float = 20.0) -> List[Tuple[str, str]]:
    """(url, reason) for every URL that doesn't answer HTTP 200."""
    failures = []
    for url in urls:
        target = url.split("#", 1)[0]
        req = urllib.request.Request(target, method="GET", headers={"User-Agent": "k9-aif-readme-check"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    failures.append((url, f"HTTP {resp.status}"))
        except Exception as exc:  # HTTPError, URLError, timeout
            failures.append((url, str(getattr(exc, "code", "") or exc)))
    return failures


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("readme", nargs="?", default=str(README))
    parser.add_argument("--check-urls", action="store_true", help="also require HTTP 200 for every http(s) URL")
    args = parser.parse_args(argv)

    text = Path(args.readme).read_text(encoding="utf-8")
    bad = relative_links(text)
    if bad:
        print(f"{args.readme}: {len(bad)} relative link(s) -- these 404 on PyPI; use absolute URLs:", file=sys.stderr)
        for line, url in bad:
            print(f"  line {line}: {url}", file=sys.stderr)
        return 1

    links = extract_links(text)
    print(f"{args.readme}: no relative links ({len(links)} links checked)")

    if args.check_urls:
        urls = sorted({u for _, u in links if u.lower().startswith(("http://", "https://"))})
        failures = check_urls(urls)
        for url, reason in failures:
            print(f"  FAIL {reason}: {url}", file=sys.stderr)
        print(f"{len(urls) - len(failures)}/{len(urls)} URLs returned HTTP 200")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
