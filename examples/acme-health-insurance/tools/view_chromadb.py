# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ChromaDB Collection Viewer (ACME HealthCare)
# Lists stored collections, their counts, and optional chunk previews.

import chromadb
from tabulate import tabulate
import logging

# ------------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------------
CHROMA_DIR = "./data/chroma"
COLLECTION_NAME = "acme_health_knowledge"
SHOW_PREVIEW = True     # Set to False to only show metadata
PREVIEW_LIMIT = 5       # Number of chunks to display per collection

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ------------------------------------------------------------------------------
# CONNECT
# ------------------------------------------------------------------------------
client = chromadb.PersistentClient(path=CHROMA_DIR)
collections = client.list_collections()

if not collections:
    logging.warning("⚠️ No collections found in ChromaDB directory.")
    exit(0)

# ------------------------------------------------------------------------------
# DISPLAY COLLECTIONS
# ------------------------------------------------------------------------------
logging.info("\n📊 Available Chroma Collections:\n")
table = [[c.name, c.count(), c.metadata] for c in collections]
print(tabulate(table, headers=["Collection", "Count", "Metadata"], tablefmt="github"))

# ------------------------------------------------------------------------------
# OPTIONAL: VIEW CHUNKS FROM SPECIFIC COLLECTION
# ------------------------------------------------------------------------------
if SHOW_PREVIEW:
    try:
        col = client.get_collection(name=COLLECTION_NAME)
        total = col.count()
        logging.info(f"\n📘 Previewing first {PREVIEW_LIMIT} chunks from '{COLLECTION_NAME}' (total: {total})\n")

        results = col.get(limit=PREVIEW_LIMIT)
        for i, doc in enumerate(results["documents"]):
            meta = results["metadatas"][i]
            logging.info(f"--- Chunk {i+1} ---")
            logging.info(f"Source: {meta.get('source')}")
            logging.info(f"Domain: {meta.get('domain')}")
            logging.info(f"Text: {doc[:350]}{'...' if len(doc) > 350 else ''}\n")

    except Exception as e:
        logging.error(f"❌ Failed to read collection '{COLLECTION_NAME}': {e}")