#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  Synthetic ACME Health Plans Loader for ChromaDB

import os, glob, requests
from k9_aif_abb.k9_persistence.chromadb_persistence import ChromaDBPersistence
from k9_aif_abb.k9_utils.config_loader import load_app_config, BASE_DIR
from k9_aif_abb.k9_factories.llm_factory import LLMFactory

# --------------------------------------------------------------------
# Synthetic plan texts (one per file)
# --------------------------------------------------------------------
PLANS = {
    "ACME_BronzeCare_Plan_2025.txt": """
ACME BronzeCare Plan 2025  Budget-friendly coverage for individuals and families.
 Monthly premium  $250
 Deductible $3 000 / $6 000 (Family)
 80 % in-network coverage after deductible
 Great for healthy members seeking catastrophic protection.
""",
    "ACME_SilverCare_Plan_2025.txt": """
ACME SilverCare Plan 2025  Balanced coverage with moderate premium and deductible.
 Monthly premium  $420
 Deductible $1 600 / $3 200 (Family)
 Covers preventive care at 100 %
 Preferred option for most ACME members.
""",
    "ACME_GoldCare_Plan_2025.txt": """
ACME GoldCare Plan 2025  Low-deductible plan for families wanting predictable costs.
 Monthly premium  $600
 Deductible $500 / $1 000 (Family)
 Comprehensive drug coverage and specialist visits included.
""",
    "ACME_PlatinumCare_Plan_2025.txt": """
ACME PlatinumCare Plan 2025  Top-tier plan with zero deductible and maximum benefits.
 Monthly premium  $850
 $0 deductible, $15 office visit copay
 Ideal for members with ongoing medical needs or frequent care.
""",
}

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"  # Use embedding model, not LLM

# --------------------------------------------------------------------
# Write files to knowledge folder
# --------------------------------------------------------------------
DATA_DIR = BASE_DIR / "k9_projects/acme_health_insurance/data/knowledge"
os.makedirs(DATA_DIR, exist_ok=True)
for fname, text in PLANS.items():
    path = DATA_DIR / fname
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip())
print(f"  Wrote {len(PLANS)} synthetic plan files  {DATA_DIR}")

# --------------------------------------------------------------------
# Load merged config & initialize Chroma persistence
# --------------------------------------------------------------------
cfg = load_app_config(
    app_name="acme_health_insurance",
    abb_config=BASE_DIR / "k9_aif_abb/config/config.yaml",
    sbb_config=BASE_DIR / "k9_projects/acme_health_insurance/config/config.yaml",
)

persist = ChromaDBPersistence(config=cfg)
collection = persist.client.get_or_create_collection("acme_health_knowledge")

# --------------------------------------------------------------------
# Clear old data safely
# --------------------------------------------------------------------
try:
    all_docs = collection.get(include=[])
    if all_docs and all_docs.get("ids"):
        collection.delete(ids=all_docs["ids"])
        print(f" Cleared {len(all_docs['ids'])} existing documents from acme_health_knowledge")
    else:
        print(" No previous documents found (clean start).")
except Exception as e:
    print(f" Could not clear old data: {e}")

# --------------------------------------------------------------------
# Embedding helper using Ollama API directly
# --------------------------------------------------------------------
def embed_texts(texts):
    """Generate embeddings using Ollama embedding API."""
    url = f"{OLLAMA_HOST}/api/embeddings"
    vectors = []
    
    for i, text in enumerate(texts):
        try:
            payload = {
                "model": EMBEDDING_MODEL,
                "prompt": text
            }
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if "embedding" in data:
                vectors.append(data["embedding"])
                print(f"   Generated embedding {i+1}/{len(texts)}")
            else:
                print(f"   No embedding in response for text {i+1}")
                vectors.append(None)
                
        except Exception as e:
            print(f"   Embedding failed for text {i+1}: {e}")
            vectors.append(None)
    
    # Filter out None values
    valid_vectors = [v for v in vectors if v is not None]
    return valid_vectors

# --------------------------------------------------------------------
# Load and insert each plan
# --------------------------------------------------------------------
count = 0
for path in sorted(glob.glob(str(DATA_DIR / "*.txt"))):
    name = os.path.basename(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        continue

    print(f" Loading {name} ({len(text)} chars)")

    # Create embeddings
    embeddings = embed_texts([text])
    
    if not embeddings or len(embeddings) == 0:
        print(f"   Skipping {name} - no valid embedding generated")
        continue

    # Insert into Chroma
    try:
        collection.add(
            ids=[f"plan_{count}"],
            documents=[text],
            embeddings=embeddings,
            metadatas=[{"source": name, "domain": "ACME HealthCare"}],
        )
        print(f" Loaded 1 chunk from {name}")
        count += 1
    except Exception as e:
        print(f"   Failed to add to ChromaDB: {e}")

print(f" Done!  Total {count} plans loaded into 'acme_health_knowledge'")