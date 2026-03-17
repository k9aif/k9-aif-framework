# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import os
import sys
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest

BASE_DIR = os.path.dirname(__file__)


class ChatAgent(BaseAgent):

    def __init__(self, config=None):
        if config is None:
            with open(os.path.join(BASE_DIR, "config.yaml")) as f:
                config = yaml.safe_load(f)

        super().__init__(config)

        if not LLMFactory.is_bootstrapped():
            LLMFactory.bootstrap(config)

        self.router = ModelRouterFactory.get_router(config)

    def execute(self, request):
        prompt = request.get("text") or request.get("prompt", "")

        inf_req = InferenceRequest(
            prompt=prompt,
            task_type="chat"
        )

        response = self.router.invoke(inf_req)

        return {
            "text": response.output,
            "model": response.model_alias
        }