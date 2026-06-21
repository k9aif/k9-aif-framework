#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — RFP Analyzer Example

"""
Demonstrates the OOB RAG pipeline processing a large RFP document.

Flow:
  1. K9DocPreprocessor — chunks the document by section
  2. K9EmbeddingAgent — generates embeddings, stores in ChromaDB
  3. K9RetrievalAgent — RAG query against indexed chunks
  4. RFPAnalysisAgent — extracts requirements, deadlines, compliance

Usage:
  python main.py
  python main.py --query "What are the compliance requirements?"
  python main.py --doc path/to/rfp.md --query "What is the timeline?"
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import yaml
from k9_aif_abb.k9_agents.rag import K9DocPreprocessor, K9EmbeddingAgent, K9RetrievalAgent
from examples.rfp_analyzer.agents.src.rfp_analysis_agent import RFPAnalysisAgent


def load_config():
    config_path = Path(__file__).parent / "config" / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_document(path: str = None) -> str:
    if path:
        with open(path) as f:
            return f.read()
    default = Path(__file__).parent / "data" / "sample_rfp.md"
    with open(default) as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(description="K9-AIF RFP Analyzer")
    parser.add_argument("--doc", help="Path to RFP document (default: sample_rfp.md)")
    parser.add_argument("--query", default="Analyze this RFP. Extract all requirements, deadlines, and compliance needs.",
                        help="Query to ask against the RFP")
    args = parser.parse_args()

    config = load_config()
    document = load_document(args.doc)

    print(f"\n{'='*60}")
    print(f"  K9-AIF RFP Analyzer")
    print(f"  Document: {len(document)} chars")
    print(f"  Query: {args.query[:80]}...")
    print(f"{'='*60}\n")

    # ── Step 1: Preprocess ──────────────────────────────────────
    print("[1/4] Preprocessing document...")
    preprocessor = K9DocPreprocessor(config=config)
    context = preprocessor.execute({"document": document})
    print(f"       Chunks: {context['chunk_count']}")
    print(f"       Sections: {context['metadata']['section_count']}")

    # ── Step 2: Embed + Index ───────────────────────────────────
    print("\n[2/4] Generating embeddings and indexing...")
    embedder = K9EmbeddingAgent(config=config)
    embed_result = embedder.execute(context)
    print(f"       Indexed: {embed_result['indexed']} chunks")
    if embed_result.get("skipped"):
        print(f"       Skipped: {embed_result['skipped']}")

    # ── Step 3: Retrieve ────────────────────────────────────────
    print(f"\n[3/4] Retrieving relevant chunks for query...")
    retriever = K9RetrievalAgent(config={**config, "top_k": 5})
    retrieval_result = retriever.execute({"query": args.query})
    print(f"       Retrieved: {retrieval_result['count']} chunks")

    # ── Step 4: Analyze ─────────────────────────────────────────
    print(f"\n[4/4] Analyzing retrieved context...")
    # Merge all context for the analysis agent
    analysis_payload = {
        **context,
        **retrieval_result,
    }
    analyzer = RFPAnalysisAgent(config=config)
    result = analyzer.execute(analysis_payload)

    print(f"\n{'='*60}")
    print(f"  RFP Analysis Result")
    print(f"{'='*60}")
    print(f"\nModel: {result.get('model_used', 'N/A')}")
    print(f"Chunks analyzed: {result.get('chunks_analyzed', 0)}")
    print(f"\n{result.get('output', 'No output')}")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
