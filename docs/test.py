# test.py — K9-AIF Hello World Agent
# Run: python test.py

import yaml
from pathlib import Path
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class HelloWorldAgent(BaseAgent):
    """Simplest possible K9-AIF agent — sends a prompt, returns the response."""

    layer = "HelloWorldAgent SBB"

    def execute(self, payload: dict) -> dict:
        name = payload.get("name", "World")

        req = InferenceRequest(
            prompt=f"Say hello to {name} in one sentence.",
            task_type="general",
        )

        resp = llm_invoke(self.config, req)

        return {
            "agent":  "HelloWorldAgent",
            "output": resp.output,
            "model":  resp.model_alias,
        }


if __name__ == "__main__":
    # Load config.yaml from same folder
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print("ERROR: config.yaml not found. Run 'k9aif init' first.")
        raise SystemExit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    print("K9-AIF Hello World")
    print("=" * 30)

    agent = HelloWorldAgent(config=config)
    result = agent.execute({"name": "K9-AIF"})

    print(f"Output : {result['output']}")
    print(f"Model  : {result['model']}")
    print()
    print("Hello World agent ran successfully.")
