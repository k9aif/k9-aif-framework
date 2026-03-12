# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ACME HealthPlanOrchestrator (SBB)
# Handles plan selection, benefit lookup, and coverage explanations.

import traceback
from typing import Dict, Any
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_projects.acme_health_insurance.agents.retriever_agent import RetrieverAgent


class HealthPlanOrchestrator(BaseOrchestrator):
    """
    HealthPlanOrchestrator
    ======================
    ACME domain orchestrator for handling plan and benefit inquiries.

    Responsibilities
    ----------------
    • Routes user questions to the :class:`RetrieverAgent` for semantic search.  
    • Retrieves relevant chunks from ChromaDB (`acme_health_knowledge`).  
    • Formats results into a human-readable Markdown reply.  
    • Publishes orchestration status updates for observability.

    Attributes
    ----------
    layer : str
        Logical name for orchestration logging and monitoring.
    """

    layer = "HealthPlan Orchestrator SBB"

    # ------------------------------------------------------------------
    async def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the plan information retrieval workflow.

        Parameters
        ----------
        payload : Dict[str, Any]
            Incoming request containing user query text.

        Returns
        -------
        Dict[str, Any]
            A structured dictionary with a formatted `reply` string.
        """
        self.logger.info(f"[{self.layer}] ▶ Execution started with payload={payload}")
        self.publish_status("started", {"event": "plan_lookup_started"})

        try:
            query = payload.get("message", "").strip()
            if not query:
                return {"reply": "Please enter a valid question about your ACME plan."}

            # ------------------------------------------------------------------
            # Step 1️⃣ — Retrieve relevant plan information
            # ------------------------------------------------------------------
            retriever = RetrieverAgent(config=self.config, monitor=self.monitor, message_bus=self.message_bus)
            retrieval = retriever.execute({
                "query": query,
                "top_k": 5,
                "collection": "acme_health_knowledge"
            })

            results = retrieval.get("results", [])
            if not results:
                self.logger.warning(f"[{self.layer}] No relevant chunks found for query='{query}'")
                self.publish_status("no_results", {"query": query})
                return {"reply": "No information found in the ACME HealthCare knowledge base."}

            # ------------------------------------------------------------------
            # Step 2️⃣ — Format structured Markdown response
            # ------------------------------------------------------------------
            reply_lines = [
                "**ACME HealthCare Plan Information:**",
                f"Your query: _{query}_",
                ""
            ]
            for idx, r in enumerate(results[:5]):
                doc = r.get("document") if isinstance(r, dict) else str(r)
                reply_lines.append(f"**{idx+1}.** {doc[:500]}...")

            reply = "\n".join(reply_lines)

            # ------------------------------------------------------------------
            # Step 3️⃣ — Publish completion event
            # ------------------------------------------------------------------
            self.publish_status("completed", {"query": query, "results": len(results)})
            self.logger.info(f"[{self.layer}] ✅ Execution complete")
            return {"reply": reply}

        except Exception as e:
            self.logger.error(f"[{self.layer}] ❌ Error: {e}")
            self.publish_status("error", {"error": str(e)})
            traceback.print_exc()
            return {"reply": "Error while processing your plan inquiry."}