# RFP Analyzer — Large Document Processing Example

Demonstrates K9-AIF's OOB RAG pipeline processing a large RFP document
through governed, chunked, vectorized analysis.

## Architecture

```
Router → RFPOrchestrator → DocumentProcessingSquad
                              ├── K9DocPreprocessor    (chunk document)
                              ├── K9EmbeddingAgent     (index in VectorDB)
                              ├── K9RetrievalAgent     (RAG query)
                              └── RFPAnalysisAgent     (extract + summarize)
```

## What It Shows

- Large document chunked by section with token-aware splitting
- Chunks indexed in ChromaDB via VectorDBFactory
- RAG retrieval against indexed chunks
- Governed analysis with audit trail
- Full context enrichment — each agent sees everything upstream

## Run

```bash
cd examples/rfp_analyzer
python main.py
```

## Config

```yaml
vectordb:
  provider: chromadb
  path: ./data/vectors
  collection: rfp_chunks
  embedding_provider: ollama
  embedding_model: nomic-embed-text
```
