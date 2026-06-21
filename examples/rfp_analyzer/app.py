#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — RFP Analyzer Web UI

"""
FastAPI web application for the RFP Analyzer.
Upload a document, watch it chunk, embed, retrieve, and analyze.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

import yaml
from k9_aif_abb.k9_agents.rag import K9DocPreprocessor, K9EmbeddingAgent, K9RetrievalAgent
from examples.rfp_analyzer.agents.src.rfp_analysis_agent import RFPAnalysisAgent

_ROOT = Path(__file__).resolve().parent
_WEBUI = _ROOT / "webui"

app = FastAPI(title="K9-AIF RFP Analyzer", version="1.0.0")

if (_WEBUI / "static").exists():
    app.mount("/static", StaticFiles(directory=str(_WEBUI / "static")), name="static")


def load_config():
    with open(_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/preprocess")
async def preprocess(file: UploadFile = File(None), text: str = Form(None)):
    config = load_config()
    if file:
        content = (await file.read()).decode("utf-8")
    elif text:
        content = text
    else:
        # Load sample
        content = open(_ROOT / "data" / "sample_rfp.md").read()

    agent = K9DocPreprocessor(config=config)
    result = agent.execute({"document": content})
    return result


@app.post("/api/embed")
async def embed(chunks: list = None):
    from fastapi import Request
    config = load_config()
    agent = K9EmbeddingAgent(config=config)
    result = agent.execute({"chunks": chunks or []})
    return result


@app.post("/api/retrieve")
async def retrieve(query: str = Form(...)):
    config = load_config()
    agent = K9RetrievalAgent(config={**config, "top_k": 5})
    result = agent.execute({"query": query})
    return result


@app.post("/api/analyze")
async def analyze(query: str = Form(...), context: str = Form(""), chunk_count: int = Form(0), count: int = Form(0)):
    config = load_config()
    agent = RFPAnalysisAgent(config=config)
    result = agent.execute({
        "query": query,
        "context": context,
        "chunk_count": chunk_count,
        "count": count,
    })
    return result


@app.post("/api/run")
async def run_full_pipeline(file: UploadFile = File(None), text: str = Form(None), query: str = Form("Analyze this RFP. Extract all requirements, deadlines, and compliance needs.")):
    """Run the full pipeline: preprocess → embed → retrieve → analyze"""
    config = load_config()

    # 1. Get document
    if file:
        content = (await file.read()).decode("utf-8")
    elif text:
        content = text
    else:
        content = open(_ROOT / "data" / "sample_rfp.md").read()

    steps = []

    # 2. Preprocess
    preprocessor = K9DocPreprocessor(config=config)
    preprocess_result = preprocessor.execute({"document": content})
    steps.append({"step": "preprocess", "agent": "K9DocPreprocessor", "result": {
        "chunk_count": preprocess_result["chunk_count"],
        "sections": preprocess_result["metadata"]["section_count"],
        "chunks": preprocess_result["chunks"],
    }})

    # 3. Embed
    embedder = K9EmbeddingAgent(config=config)
    embed_result = embedder.execute(preprocess_result)
    steps.append({"step": "embed", "agent": "K9EmbeddingAgent", "result": {
        "indexed": embed_result["indexed"],
        "skipped": embed_result.get("skipped", 0),
    }})

    # 4. Retrieve
    retriever = K9RetrievalAgent(config={**config, "top_k": 5})
    retrieval_result = retriever.execute({"query": query})
    steps.append({"step": "retrieve", "agent": "K9RetrievalAgent", "result": {
        "count": retrieval_result["count"],
        "retrieved": retrieval_result["retrieved"],
    }})

    # 5. Analyze
    analysis_payload = {**preprocess_result, **retrieval_result}
    analyzer = RFPAnalysisAgent(config=config)
    analysis_result = analyzer.execute(analysis_payload)
    steps.append({"step": "analyze", "agent": "RFPAnalysisAgent", "result": {
        "output": analysis_result.get("output", ""),
        "model_used": analysis_result.get("model_used", ""),
    }})

    return {"steps": steps, "query": query}


@app.get("/{full_path:path}")
def serve_ui(full_path: str):
    index = _WEBUI / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "webui not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8087, reload=True)
