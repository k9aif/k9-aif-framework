# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  ChatAgent (SBB)
# Uses K9ModelRouter to answer user questions with optional context.

from typing import Dict, Any
import traceback

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter


class ChatAgent(BaseAgent):
    """Answers user messages via the configured K9 Model Router."""
    layer = "Chat SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initialized ChatAgent")

        try:
            self.catalog = ModelCatalog(self.config)
            self.router = K9ModelRouter(self.catalog)
            self.logger.info(f"[{self.layer}]  K9ModelRouter ready")
        except Exception as e:
            self.catalog = None
            self.router = None
            self.logger.error(f"[{self.layer}]  Could not initialize K9ModelRouter: {e}")

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        payload:
          {
            "message": "Tell me more about SilverCare",
            "context": "Optional short context to bias the answer"
          }
        returns:
          { "reply": "<string>" }
        """
        user_msg = (payload or {}).get("message", "")
        context = (payload or {}).get("context", "")

        if not user_msg:
            return {"reply": " Please enter a message."}

        self.log(f"[{self.layer}]  ACME ChatAgent started: '{user_msg}'")

        prompt = (
            "You are ACME HealthCare's helpful assistant.\n"
            "Be concise, factual, and user-friendly.\n"
        )
        if context:
            prompt += f"\nContext:\n{context}\n"
        prompt += f"\nUser: {user_msg}\nAssistant:"

        try:
            if self.router is None:
                raise RuntimeError("K9ModelRouter not initialized")

            req = InferenceRequest(
                prompt=prompt,
                task_type="chat",
                metadata={"agent": "chat_agent"}
            )

            response = self.router.invoke(req)

            text = (response.output or "").strip()
            if not text:
                text = "I couldn't generate a response."

            self.log(
                f"[{self.layer}]  Router responded successfully "
                f"(model={response.model_alias}, provider={response.provider})."
            )
            return {"reply": text}

        except Exception as e:
            self.log(f"[{self.layer}]  Router invocation failed: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": " An internal error occurred while generating a response."}