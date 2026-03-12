# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  Direct Knowledge Loader (no ABB)
# Parses PDF  creates embeddings (Ollama)  stores in ChromaDB

import os, hashlib, logging, requests, chromadb
from pathlib import Path
from typing import List
from PyPDF2 import PdfReader

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
PDF_PATH = "./k9_projects/acme_health_insurance/data/knowledge/K9-AIF_Framework_Natarajan_v1.2.pdf"
CHROMA_DIR = "./data/chroma"
COLLECTION_NAME = "k9_aif_framework_v1_2"
CHUNK_SIZE = 900
OVERLAP = 120
OLLAMA_HOST = "http://192.168.1.98:11434"  # Your Ollama server
OLLAMA_MODEL = "nomic-embed-text"

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ------------------------------------------------------------------------------
# TEXT EXTRACTOR
# ------------------------------------------------------------------------------
def read_pdf(path: Path) -> str:
    """Extract text from PDF file."""
    try:
        reader = PdfReader(str(path))
        text = "\n".join([p.extract_text() or "" for p in reader.pages])
        logging.info(f" Extracted {len(text)} characters from {len(reader.pages)} pages")
        return text
    except Exception as e:
        logging.error(f" Failed to read PDF: {e}")
        raise

# ------------------------------------------------------------------------------
# CHUNKER
# ------------------------------------------------------------------------------
def split_text(text: str, chunk_size=900, overlap=120) -> List[str]:
    """Split text into overlapping chunks."""
    text = text.strip()
    if not text:
        logging.warning(" Empty text provided to chunker")
        return []
    
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end].strip()
        if chunk:  # Only add non-empty chunks
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    
    logging.info(f" Created {len(chunks)} chunks (size={chunk_size}, overlap={overlap})")
    return chunks

# ------------------------------------------------------------------------------
# OLLAMA EMBEDDER (FIXED)
# ------------------------------------------------------------------------------
def embed_with_ollama(texts: List[str], model: str = OLLAMA_MODEL) -> List[List[float]]:
    """
    Generate embeddings using Ollama API.
    Processes one text at a time to avoid batch format issues.
    """
    url = f"{OLLAMA_HOST}/api/embeddings"
    all_embeds = []
    
    logging.info(f" Generating embeddings for {len(texts)} chunks using {model}...")
    
    for i, text in enumerate(texts):
        if i % 10 == 0:
            logging.info(f"   Processing chunk {i+1}/{len(texts)}...")
        
        payload = {
            "model": model,
            "prompt": text  # Ollama uses "prompt" not "input"
        }
        
        try:
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            
            # Ollama returns {"embedding": [...]}
            if "embedding" in data:
                embedding = data["embedding"]
                if isinstance(embedding, list) and len(embedding) > 0:
                    all_embeds.append(embedding)
                else:
                    logging.error(f" Empty embedding for chunk {i}")
            else:
                logging.error(f" Unexpected response format for chunk {i}: {data}")
                
        except requests.exceptions.RequestException as e:
            logging.error(f" Request failed for chunk {i}: {e}")
        except Exception as e:
            logging.error(f" Unexpected error for chunk {i}: {e}")
    
    logging.info(f" Generated {len(all_embeds)} embeddings")
    return all_embeds

# ------------------------------------------------------------------------------
# VECTOR STORE LOADER
# ------------------------------------------------------------------------------
def hash_id(source: str, i: int, chunk: str) -> str:
    """Generate unique hash ID for each chunk."""
    return hashlib.sha256(f"{source}-{i}-{chunk[:50]}".encode()).hexdigest()

def load_to_chroma():
    """Main pipeline: PDF  Chunks  Embeddings  ChromaDB"""
    path = Path(PDF_PATH)
    
    if not path.exists():
        logging.error(f" PDF not found: {path}")
        return
    
    logging.info(f" Reading PDF: {path}")
    text = read_pdf(path)
    
    if not text.strip():
        logging.error(" No text extracted from PDF")
        return
    
    chunks = split_text(text, CHUNK_SIZE, OVERLAP)
    
    if not chunks:
        logging.error(" No chunks created")
        return
    
    embeddings = embed_with_ollama(chunks)
    
    if len(embeddings) != len(chunks):
        logging.warning(f" Mismatch: {len(chunks)} chunks but {len(embeddings)} embeddings")
        # Only keep chunks that have embeddings
        chunks = chunks[:len(embeddings)]
    
    if not embeddings:
        logging.error(" No embeddings generated")
        return
    
    logging.info(f" Storing {len(embeddings)} chunks in ChromaDB...")
    
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        col = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "K9-AIF Framework Knowledge Base"}
        )
        
        ids = [hash_id(path.name, i, c) for i, c in enumerate(chunks)]
        metadatas = [{"source": path.name, "chunk_id": i, "domain": "K9-AIF Technical"} 
                     for i in range(len(chunks))]
        
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas
        )
        
        logging.info(f" Successfully loaded {len(chunks)} chunks into collection '{COLLECTION_NAME}'")
        logging.info(f" Collection now has {col.count()} total documents")
        
    except Exception as e:
        logging.error(f" ChromaDB storage failed: {e}")
        raise

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        load_to_chroma()
    except Exception as e:
        logging.error(f" Pipeline failed: {e}")
        import traceback
        traceback.print_exc()