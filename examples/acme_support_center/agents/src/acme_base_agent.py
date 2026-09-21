# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from typing import Dict, Any
import logging

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke

log = logging.getLogger(__name__)


class AcmeBaseAgent(BaseAgent):

    def __init__(self, config=None):
        config = config or {}
        super().__init__(config)

        self.config = config
        self.tools = {}

    def run_inference(self, prompt, task_type="support"):
        inf_req = InferenceRequest(
            prompt=prompt,
            task_type=task_type
        )

        response = llm_invoke(self.config, inf_req)

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