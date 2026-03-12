from k9_aif_abb.k9_core.agent.base_agent import BaseAgent

class CrewGovernedAgent(BaseAgent):
    """
    A governed CrewAI agent that executes a task via LLMFactory,
    protected by governance policies.
    """

    layer = "CrewAI SBB"

    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)
        # Load the LLM model via LLMFactory
        try:
            from k9_aif_abb.k9_factories.llm_factory import LLMFactory
            self.llm = LLMFactory.create(self.config)
            self.log("LLMFactory initialized successfully.")
        except Exception as e:
            self.llm = None
            self.log(f"LLMFactory unavailable: {e}")

    async def execute(self, payload):
        self.enforce_governance(stage="pre")

        if not self.llm:
            raise RuntimeError("LLMFactory not initialized or model missing")

        prompt = payload.get("prompt", "")
        response = await self.llm.generate(prompt)

        # Store response for post-governance inspection
        self.config["last_output"] = response
        self.enforce_governance(stage="post")

        return {"response": response}