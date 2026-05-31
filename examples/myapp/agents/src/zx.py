from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class Zx(BaseAgent):

    layer = "myapp Zx SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            f"Role: {self.config.get('role', '')}\n"
            f"Goal: {self.config.get('goal', '')}\n\n"
            f"Input: {payload}"
        )
        req = InferenceRequest(
            prompt=prompt,
            task_type=self.config.get("model", "general"),
            metadata={"agent": "Zx"},
        )
        try:
            resp = llm_invoke(self.config, req)
        except RuntimeError as exc:
            self.logger.error("[%s] LLM unavailable: %s", self.layer, exc)
            return {"agent": "Zx", "output": "[WARN] LLM unavailable", "confidence": 0.0}

        self.publish_event({"type": "ZxCompleted", "agent": "Zx"})
        return {
            "agent": "Zx",
            "output": resp.output.strip(),
            "model_used": resp.model_alias,
        }
