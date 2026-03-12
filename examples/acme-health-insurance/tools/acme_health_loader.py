# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ACME HealthCare Knowledge Loader (Direct)
# One-time ingestion: PDFs → Chunks → Embeddings → ChromaDB
# Embeddings: Ollama (nomic-embed-text)

import os, hashlib, logging, requests, chromadb
from pathlib import Path
from typing import List
from PyPDF2 import PdfReader

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
PDF_MAP = {
    "./k9_projects/acme_health_insurance/data/knowledge/2024 TRS-Care Standard Summary of Benefits_0.pdf": "ACME SilverCare Plan",
    "./k9_projects/acme_health_insurance/data/knowledge/sbc-gh3d46bftitxp-tx-2025.pdf": "ACME GoldPlus Plan",
}

CHROMA_DIR = "./data/chroma"
COLLECTION_NAME = "acme_health_knowledge"
CHUNK_SIZE = 900
OVERLAP = 120
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "nomic-embed-text"

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ------------------------------------------------------------------------------
# Text Sanitization / Branding
# ------------------------------------------------------------------------------
def sanitize_text(raw: str) -> str:
    """
    Cleans and rebrands plan text to ACME HealthCare context.
    Keeps factual data but removes direct insurer names and disclaimers.
    """
    text = raw

    replacements = {
        "Blue Cross Blue Shield": "ACME HealthCare (in partnership with Blue Cross Blue Shield)",
        "BlueCross BlueShield": "ACME HealthCare (Blue Cross Blue Shield partner)",
        "BlueCross Blue Shield": "ACME HealthCare (Blue Cross Blue Shield partner)",
        "BCBS": "ACME HealthCare (Blue Cross partner)",
        "B C B S": "ACME HealthCare (Blue Cross partner)",
        "TRS-Care": "ACME SilverCare",
        "TRS Care": "ACME SilverCare",
        "Kaiser Permanente": "ACME HealthCare",
        "UnitedHealthcare": "ACME HealthCare",
        "United Healthcare": "ACME HealthCare",
        "Ambetter": "ACME HealthCare",
        "Plan Administrator": "ACME Plan Administrator",
        "Blue Advantage": "ACME Advantage",
        "Blue Choice": "ACME Choice",
        "Texas": "our service area",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove unnecessary disclaimers
    lines = text.splitlines()
    cleaned = [
        l for l in lines
        if not any(k in l.lower() for k in ["this document is provided by", "©", "copyright", "all rights reserved"])
    ]
    text = "\n".join(cleaned)

    # Normalize spacing
    text = " ".join(text.split())
    return text.strip()

# ------------------------------------------------------------------------------
# PDF Reader
# ------------------------------------------------------------------------------
def read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        text = "\n".join([p.extract_text() or "" for p in reader.pages])
        text = sanitize_text(text)
        logging.info(f"📄 Extracted & sanitized {len(text)} characters from {path.name}")
        return text
    except Exception as e:
        logging.error(f"❌ Failed to read PDF {path}: {e}")
        return ""

# ------------------------------------------------------------------------------
# Chunker
# ------------------------------------------------------------------------------
def split_text(text: str, chunk_size=900, overlap=120) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

# ------------------------------------------------------------------------------
# Embedder
# ------------------------------------------------------------------------------
def embed_with_ollama(texts: List[str]) -> List[List[float]]:
    url = f"{OLLAMA_HOST}/api/embeddings"
    all_embeds = []
    for i, text in enumerate(texts):
        logging.info(f"🧠 Chunk {i+1}/{len(texts)}")
        try:
            r = requests.post(url, json={"model": OLLAMA_MODEL, "prompt": text}, timeout=120)
            r.raise_for_status()
            data = r.json()
            emb = data.get("embedding")
            if emb and isinstance(emb, list):
                all_embeds.append(emb)
        except Exception as e:
            logging.warning(f"⚠️ Skipped chunk {i}: {e}")
    logging.info(f"✅ Generated {len(all_embeds)} embeddings")
    return all_embeds

# ------------------------------------------------------------------------------
# Chroma Loader
# ------------------------------------------------------------------------------
def hash_id(source: str, i: int, chunk: str) -> str:
    return hashlib.sha256(f"{source}-{i}-{chunk[:50]}".encode()).hexdigest()

def load_to_chroma():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "ACME HealthCare Plans Knowledge Base"}
    )

    total_chunks = 0
    for pdf, acme_name in PDF_MAP.items():
        path = Path(pdf)
        if not path.exists():
            logging.warning(f"⚠️ Missing file: {pdf}")
            continue

        text = read_pdf(path)
        chunks = split_text(text, CHUNK_SIZE, OVERLAP)
        if not chunks:
            continue

        embeddings = embed_with_ollama(chunks)
        if not embeddings:
            continue

        chunks = chunks[:len(embeddings)]
        ids = [hash_id(acme_name, i, c) for i, c in enumerate(chunks)]
        metadatas = [{"source": acme_name, "chunk_id": i, "domain": "ACME HealthCare"} for i in range(len(chunks))]

        col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        total_chunks += len(chunks)
        logging.info(f"💾 Loaded {len(chunks)} chunks → {acme_name}")

    logging.info(f"✅ ACME HealthCare ingestion complete — {total_chunks} total chunks")
    logging.info(f"📊 Collection '{COLLECTION_NAME}' now has {col.count()} documents")

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        load_to_chroma()
    except Exception as e:
        logging.error(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()