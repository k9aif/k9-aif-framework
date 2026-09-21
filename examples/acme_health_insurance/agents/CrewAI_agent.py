# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class CrewGovernedAgent(BaseAgent):
    """
    A governed CrewAI agent that executes a task via the K9 Model Router,
    protected by governance policies.
    """

    layer = "CrewAI SBB"

    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)

    async def execute(self, payload):
        self.enforce_governance(stage="pre")

        prompt = payload.get("prompt", "")

        req = InferenceRequest(
            prompt=prompt,
            task_type="chat",
            metadata={"agent": "crewai_governed_agent"},
        )

        response = llm_invoke(self.config, req)
        output = response.output

        # Store response for post-governance inspection
        self.config["last_output"] = output
        self.enforce_governance(stage="post")

        return {"response": output}