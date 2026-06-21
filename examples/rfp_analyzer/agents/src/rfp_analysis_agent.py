# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""RFP Analysis Agent — extracts requirements, deadlines, compliance from retrieved RFP context."""

from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class RFPAnalysisAgent(BaseAgent):

    layer = "RFP Analyzer SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        context = payload.get("context", "")
        query = payload.get("query", "Analyze this RFP document")
        chunk_count = payload.get("chunk_count", 0)
        retrieved_count = payload.get("count", 0)

        if not context:
            return {
                "agent": "RFPAnalysisAgent",
                "output": "No context retrieved for analysis",
                "confidence": 0.0,
            }

        prompt = (
            f"Role: {self.config.get('role', 'RFP Analyst')}\n"
            f"Goal: {self.config.get('goal', 'Extract structured information from RFP')}\n\n"
            f"The following are retrieved sections from an RFP document "
            f"({chunk_count} total chunks, {retrieved_count} retrieved):\n\n"
            f"---\n{context}\n---\n\n"
            f"Query: {query}\n\n"
            f"Provide a structured analysis with: requirements, deadlines, "
            f"compliance needs, evaluation criteria, and an executive summary. "
            f"Include a confidence score (0.0-1.0) for completeness."
        )

        req = InferenceRequest(
            prompt=prompt,
            task_type="reasoning",
            metadata={"agent": "RFPAnalysisAgent", "chunks_analyzed": retrieved_count},
        )

        try:
            resp = llm_invoke(self.config, req)
            output = resp.output.strip()
        except RuntimeError as exc:
            self.logger.error("[%s] LLM unavailable: %s", self.layer, exc)
            output = f"[WARN] LLM unavailable: {exc}"

        self.publish_event({
            "type": "RFPAnalysisCompleted",
            "chunks_analyzed": retrieved_count,
        })

        return {
            "agent": "RFPAnalysisAgent",
            "output": output,
            "model_used": getattr(resp, "model_alias", "unknown") if "resp" in dir() else "unavailable",
            "chunks_analyzed": retrieved_count,
        }
