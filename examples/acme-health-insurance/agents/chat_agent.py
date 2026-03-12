# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™ — ChatAgent (SBB)
# Uses LLMFactory to answer user questions with optional context.

from typing import Dict, Any
import traceback

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


def _to_text(resp) -> str:
    """
    Normalize various LLM response shapes into a plain string.
    Supports strings, dicts with 'text'/'output' keys, or objects with .text.
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("text", "output", "content", "message"):
            if k in resp and isinstance(resp[k], str):
                return resp[k]
    # Some clients return objects with .text or .output_text
    for attr in ("text", "output_text", "generated_text", "content"):
        if hasattr(resp, attr):
            val = getattr(resp, attr)
            if isinstance(val, str):
                return val
    # Fallback to repr (better than returning a coroutine repr upstream)
    return str(resp)


class ChatAgent(BaseAgent):
    """Answers user messages via the configured LLM (through LLMFactory)."""
    layer = "Chat SBB"

    def __init__(self, config=None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.logger.info(f"[{self.layer}] Initialized ChatAgent")

        try:
            # LLMFactory should have been bootstrapped during app startup.
            self.llm = LLMFactory.get("general")
            self.logger.info(f"[{self.layer}] ✅ LLM ready via LLMFactory (general)")
        except Exception as e:
            self.llm = None
            self.logger.error(f"[{self.layer}] ❌ Could not acquire LLM: {e}")

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
        context  = (payload or {}).get("context", "")

        if not user_msg:
            return {"reply": "⚠️ Please enter a message."}

        self.log(f"[{self.layer}] ▶ ACME ChatAgent started: '{user_msg}'")

        # Build a clean, deterministic prompt
        prompt = (
            "You are ACME HealthCare's helpful assistant.\n"
            "Be concise, factual, and user-friendly.\n"
        )
        if context:
            prompt += f"\nContext:\n{context}\n"
        prompt += f"\nUser: {user_msg}\nAssistant:"

        # --- Call LLM (support both async and sync variants) ---
        try:
            text = ""
            if self.llm is None:
                raise RuntimeError("LLM not initialized")

            # Prefer ainvoke if available
            if hasattr(self.llm, "ainvoke") and callable(self.llm.ainvoke):
                resp = await self.llm.ainvoke(prompt)
                text = _to_text(resp)

            # Fallback: agenerate
            elif hasattr(self.llm, "agenerate") and callable(self.llm.agenerate):
                resp = await self.llm.agenerate(prompt)
                text = _to_text(resp)

            # Sync paths (rare in your setup, but kept for completeness)
            elif hasattr(self.llm, "invoke") and callable(self.llm.invoke):
                resp = self.llm.invoke(prompt)
                text = _to_text(resp)

            elif hasattr(self.llm, "generate") and callable(self.llm.generate):
                resp = self.llm.generate(prompt)
                text = _to_text(resp)

            else:
                raise RuntimeError("No compatible LLM method found (ainvoke/agenerate/invoke/generate).")

            text = (text or "").strip()
            if not text:
                text = "I couldn't generate a response."

            self.log(f"[{self.layer}] ✅ LLM responded successfully.")
            return {"reply": text}

        except Exception as e:
            self.log(f"[{self.layer}] ❌ LLM invocation failed: {e}", level="ERROR")
            traceback.print_exc()
            return {"reply": "⚠️ An internal error occurred while generating a response."}