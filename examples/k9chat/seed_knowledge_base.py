# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# Seeds the k9chat knowledge base (KnowledgeRetriever's fixed ChromaDB
# collection) with the real K9-AIF framework + K9X ecosystem documentation,
# blog corpus, and developer guides -- chunked and embedded the same way
# dow-k9-aif's seed_synthetic_corpus.py seeds its corpus.
#
# Deliberately docs/prose-only, not raw .py source: code chunks retrieved
# out of context tend to mislead more than help for a "chat and learn about
# the framework" use case. Raw source is better served by a dedicated
# code-search tool later, not mixed into this general knowledge base.
#
# Idempotent-ish: re-running re-embeds and re-stores every chunk under the
# same doc_ids (doc_id = f"{label}:{i}"), so ChromaDB upserts rather than
# duplicating -- safe to re-run after any of these docs change.
#
# Usage (from the k9-aif-framework repo root):
#   python -m examples.k9chat.seed_knowledge_base

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import re

from k9_aif_abb.k9_utils.config_loader import load_yaml
from examples.k9chat.knowledge_retriever import KnowledgeRetriever, COLLECTION_NAME
from examples.k9chat.project_retriever import chunk_text

BASE_DIR = os.path.dirname(__file__)
FRAMEWORK_ROOT = Path(REPO_ROOT)
ECOSYSTEM_ROOT = FRAMEWORK_ROOT.parent / "k9x-ecosystem"
DOW_ROOT = FRAMEWORK_ROOT.parent / "dow-k9-aif"
BLOGS_ROOT = FRAMEWORK_ROOT.parent / "k9-aif-blogs" / "_posts"
DOIT_ASSETS = FRAMEWORK_ROOT.parent / "doit" / "assets"

# (label, path) -- label becomes both the doc_id prefix and the
# "[label] chunk text" filename tag chunk_text() already applies.
# Every path is checked for existence at seed time; a moved/renamed file
# is skipped with a warning, never a hard failure -- one missing doc
# shouldn't block seeding the rest.
TEXT_CORPUS: list[tuple[str, Path]] = [
    # Short, dense, one-definition-per-term -- deliberately first, and
    # deliberately separate from the long-form docs below. Added
    # 2026-09-20 after a real retrieval-quality gap: semantic search over
    # long-form README/blog prose kept losing a single definitional
    # sentence to broader tangential passages, so "what does ABB stand
    # for" never actually surfaced the real definition and the model
    # answered wrong from its own prior knowledge instead.
    ("k9chat/glossary", Path(BASE_DIR) / "knowledge" / "glossary.md"),
    ("k9-aif-framework/CLAUDE.md", FRAMEWORK_ROOT / "CLAUDE.md"),
    ("k9-aif-framework/SKILLS.md", FRAMEWORK_ROOT / "SKILLS.md"),
    ("k9-aif-framework/README.md", FRAMEWORK_ROOT / "README.md"),
    ("k9-aif-framework/k9_security/CLAUDE.md",
     FRAMEWORK_ROOT / "k9_aif_abb/k9_security/CLAUDE.md"),
    ("k9x-ecosystem/CLAUDE.md", ECOSYSTEM_ROOT / "CLAUDE.md"),
    ("k9x-ecosystem/README.md", ECOSYSTEM_ROOT / "README.md"),
    ("k9x-ecosystem/k9x_satan/CLAUDE.md", ECOSYSTEM_ROOT / "k9x_satan/CLAUDE.md"),
    ("k9x-ecosystem/k9x_studio/README.md", ECOSYSTEM_ROOT / "k9x_studio/README.md"),
    ("k9x-ecosystem/k9x_continuum/README.md", ECOSYSTEM_ROOT / "k9x_continuum/README.md"),
    ("k9x-ecosystem/k9x_enterprise_repository/README.md",
     ECOSYSTEM_ROOT / "k9x_enterprise_repository/README.md"),
    ("k9x-ecosystem/k9x_testcases/README.md", ECOSYSTEM_ROOT / "k9x_testcases/README.md"),
    ("k9x-ecosystem/k9x_coe/README.md", ECOSYSTEM_ROOT / "k9x_coe/README.md"),
    ("dow-k9-aif/CLAUDE.md", DOW_ROOT / "CLAUDE.md"),
    ("dow-k9-aif/README.md", DOW_ROOT / "README.md"),
]

# Docs chunked one-section-per-"## heading" instead of chunk_text()'s
# paragraph-merging. Confirmed 2026-09-20: merging multiple glossary
# terms into one chunk diluted the ABB definition's embedding (a real
# question, "what does ABB stand for", couldn't retrieve it) -- a
# glossary needs each fact to embed distinctly on its own, never merged
# with its neighbors.
HEADING_CHUNKED = {"k9chat/glossary"}


def _chunk_by_heading(text: str, filename: str) -> list[str]:
    sections = re.split(r"\n(?=## )", text)
    return [f"[{filename}] {s.strip()}" for s in sections if s.strip()]


# PDFs need text extraction (pypdf, already in requirements.txt) rather
# than a plain read_text().
PDF_CORPUS: list[tuple[str, Path]] = [
    ("k9-aif-developer-guide", DOIT_ASSETS / "Developer-guide.pdf"),
    ("k9-aif-quick-start-guide", DOIT_ASSETS / "Quick-Start-Guide.pdf"),
]


def _extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _iter_corpus():
    """Yields (label, path, reader) for every doc in the corpus -- static
    text files, PDFs, and every blog post found under k9-aif-blogs/_posts
    (globbed, not hardcoded, so new posts get picked up automatically on
    the next seed run without editing this file)."""
    for label, path in TEXT_CORPUS:
        yield label, path, lambda p: p.read_text(encoding="utf-8")

    for label, path in PDF_CORPUS:
        yield label, path, _extract_pdf_text

    if BLOGS_ROOT.exists():
        for post_path in sorted(BLOGS_ROOT.glob("*.md")):
            label = f"k9-aif-blogs/{post_path.stem}"
            yield label, post_path, lambda p: p.read_text(encoding="utf-8")


def main() -> None:
    config = load_yaml(os.path.join(BASE_DIR, "config.yaml"))
    retriever = KnowledgeRetriever(config)

    total_docs = 0
    total_chunks = 0
    skipped: list[str] = []
    failed: list[str] = []

    for label, path, reader in _iter_corpus():
        if not path.exists():
            skipped.append(f"{label} ({path})")
            continue

        try:
            text = reader(path)
        except Exception as exc:
            failed.append(f"{label}: {exc}")
            continue

        chunker = _chunk_by_heading if label in HEADING_CHUNKED else chunk_text
        chunks = chunker(text, label)  # already prefixes each chunk "[label] ..."
        stored = 0
        for i, chunk in enumerate(chunks):
            ok = retriever.store_chunk(
                doc_id=f"{label}:{i}",
                text=chunk,
                metadata={
                    "text": chunk,
                    "source": label,
                    "chunk_index": i,
                },
            )
            if ok:
                stored += 1

        print(f"[seed] {label}: {stored}/{len(chunks)} chunks stored")
        total_docs += 1
        total_chunks += stored

    print(f"\n[seed] Done. {total_docs} documents, {total_chunks} chunks stored "
          f"into collection '{COLLECTION_NAME}'.")

    if skipped:
        print(f"\n[seed] Skipped {len(skipped)} missing file(s) (not an error, just not found):")
        for s in skipped:
            print(f"  - {s}")

    if failed:
        print(f"\n[seed] Failed to read {len(failed)} file(s):")
        for f in failed:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
