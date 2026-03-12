"""
Utility for loading framework documentation into a vector store.

This script:
1. Reads a PDF file
2. Splits the extracted text into overlapping chunks
3. Generates embeddings using an Ollama embedding model
4. Stores the chunks and embeddings in ChromaDB

Environment variables (optional):
- PDF_PATH: path to the PDF file to ingest
- CHROMA_DIR: directory for ChromaDB persistence
- COLLECTION_NAME: target ChromaDB collection name
- CHUNK_SIZE: text chunk size
- OVERLAP: overlap between chunks
- OLLAMA_HOST: Ollama server URL
- OLLAMA_MODEL: embedding model name
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import List

import chromadb
import requests
from PyPDF2 import PdfReader

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------

PDF_PATH = os.getenv("PDF_PATH", "./input/document.pdf")
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "k9_aif_framework")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "900"))
OVERLAP = int(os.getenv("OVERLAP", "120"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nomic-embed-text")

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ------------------------------------------------------------------------------
# PDF READER
# ------------------------------------------------------------------------------

def read_pdf(path: Path) -> str:
    """Extract text content from a PDF file."""
    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        logging.info(
            "Extracted %s characters from %s pages",
            len(text),
            len(reader.pages),
        )
        return text
    except Exception as exc:
        logging.error("Failed to read PDF: %s", exc)
        raise


# ------------------------------------------------------------------------------
# TEXT CHUNKING
# ------------------------------------------------------------------------------

def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    """Split text into overlapping chunks."""
    text = text.strip()
    if not text:
        logging.warning("Empty text provided for chunking")
        return []

    chunks: List[str] = []
    start = 0
    total_len = len(text)

    while start < total_len:
        end = min(start + chunk_size, total_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end == total_len:
            break

        start = max(0, end - overlap)

    logging.info(
        "Created %s chunks (chunk_size=%s, overlap=%s)",
        len(chunks),
        chunk_size,
        overlap,
    )
    return chunks


# ------------------------------------------------------------------------------
# EMBEDDINGS
# ------------------------------------------------------------------------------

def embed_with_ollama(texts: List[str], model: str = OLLAMA_MODEL) -> List[List[float]]:
    """
    Generate embeddings using the Ollama embeddings API.

    Processes one text at a time to keep error handling simple and explicit.
    """
    url = f"{OLLAMA_HOST}/api/embeddings"
    embeddings: List[List[float]] = []

    logging.info("Generating embeddings for %s chunks using model '%s'...", len(texts), model)

    for index, text in enumerate(texts):
        if index % 10 == 0:
            logging.info("Processing chunk %s/%s...", index + 1, len(texts))

        payload = {
            "model": model,
            "prompt": text,
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()

            embedding = data.get("embedding")
            if isinstance(embedding, list) and embedding:
                embeddings.append(embedding)
            else:
                logging.error("Unexpected embedding response for chunk %s: %s", index, data)

        except requests.exceptions.RequestException as exc:
            logging.error("Embedding request failed for chunk %s: %s", index, exc)
        except Exception as exc:
            logging.error("Unexpected error for chunk %s: %s", index, exc)

    logging.info("Generated %s embeddings", len(embeddings))
    return embeddings


# ------------------------------------------------------------------------------
# VECTOR STORE
# ------------------------------------------------------------------------------

def hash_id(source: str, index: int, chunk: str) -> str:
    """Generate a stable ID for each chunk."""
    seed = f"{source}-{index}-{chunk[:80]}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def load_to_chroma() -> None:
    """Run the full ingestion pipeline: PDF -> chunks -> embeddings -> ChromaDB."""
    pdf_path = Path(PDF_PATH)

    if not pdf_path.exists():
        logging.error("PDF file not found: %s", pdf_path)
        return

    logging.info("Reading PDF: %s", pdf_path)
    text = read_pdf(pdf_path)

    if not text.strip():
        logging.error("No text extracted from PDF")
        return

    chunks = split_text(text, CHUNK_SIZE, OVERLAP)
    if not chunks:
        logging.error("No chunks created")
        return

    embeddings = embed_with_ollama(chunks)
    if not embeddings:
        logging.error("No embeddings generated")
        return

    if len(embeddings) != len(chunks):
        logging.warning(
            "Chunk/embedding mismatch: %s chunks, %s embeddings",
            len(chunks),
            len(embeddings),
        )
        chunks = chunks[: len(embeddings)]

    logging.info("Storing %s chunks in ChromaDB...", len(embeddings))

    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Framework documentation knowledge base"},
        )

        ids = [hash_id(pdf_path.name, i, chunk) for i, chunk in enumerate(chunks)]
        metadatas = [
            {
                "source": pdf_path.name,
                "chunk_id": i,
                "domain": "framework_documentation",
            }
            for i in range(len(chunks))
        ]

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        logging.info(
            "Successfully loaded %s chunks into collection '%s'",
            len(chunks),
            COLLECTION_NAME,
        )
        logging.info("Collection now contains %s documents", collection.count())

    except Exception as exc:
        logging.error("ChromaDB storage failed: %s", exc)
        raise


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        load_to_chroma()
    except Exception as exc:
        logging.error("Pipeline failed: %s", exc)
        import traceback
        traceback.print_exc()
