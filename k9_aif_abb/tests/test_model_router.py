# tests/test_model_router.py

from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest


CONFIG = {
    "inference": {
        "router": {
            "type": "k9"
        },
        "llm_factory": {
            "provider": "ollama",
            "base_url": "http://192.168.1.98:11434",
            "models": {
                "general": "llama3.2:1b"
            }
        },
        "model_catalog": {
            "default_model": "general",
            "models": {
                "general": {
                    "provider": "ollama",
                    "llm_ref": "general",
                    "capabilities": ["chat"]
                }
            }
        }
    }
}


def main():

    print("\n--- Bootstrapping LLMFactory ---")
    LLMFactory.bootstrap(CONFIG)

    print("\n--- Creating Router ---")
    router = ModelRouterFactory.get_router(CONFIG)

    print(f"Router type: {router.__class__.__name__}")

    request = InferenceRequest(
        prompt="Explain what K9-AIF architecture is.",
        task_type="chat"
    )

    print("\n--- Invoking Router ---")
    response = router.invoke(request)

    print("\n--- Response ---")
    print("Model:", response.model_alias)
    print("Output:", response.output)


if __name__ == "__main__":
    main()