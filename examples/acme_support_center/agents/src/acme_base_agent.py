# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from typing import Dict, Any
import logging

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest

log = logging.getLogger(__name__)


class AcmeBaseAgent(BaseAgent):

    def __init__(self, config=None):
        config = config or {}
        super().__init__(config)

        self.config = config
        self.tools = {}
        self.router = ModelRouterFactory.get_router(config)

    def run_inference(self, prompt, task_type="support"):
        inf_req = InferenceRequest(
            prompt=prompt,
            task_type=task_type
        )

        response = self.router.invoke(inf_req)

        return {
            "text": response.output,
            "model": response.model_alias
        }

    def call_tool(self, tool_name: str, payload: Dict[str, Any]) -> Any:
        tool = getattr(self, "tools", {}).get(tool_name)
        if tool is None:
            return None

        try:
            if hasattr(tool, "run") and callable(tool.run):
                return tool.run(payload)
            if callable(tool):
                return tool(payload)
        except Exception as exc:
            log.exception("Tool '%s' failed in %s: %s", tool_name, self.__class__.__name__, exc)
            return {"error": str(exc)}

        return None

    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        text = request.get("text") or request.get("prompt", "")
        return self.run(text, request)