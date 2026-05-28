# K9X LLM Bridge Adapter — Roadmap

## The Gap

K9-AIF governs orchestration boundaries (Router, Orchestrator, Agent, Squad).
But LLM calls from third-party frameworks (CrewAI, LangChain, AutoGen) bypass
K9ModelRouter entirely — no routing telemetry, no governance, no audit trail.

K9-AIF is not yet a true AI motherboard.

## The Vision

Every LLM call, from any framework, routes through K9ModelRouter.
The `K9XLLMBridgeAdapter` family is the universal LLM bus.

## Naming Convention

`K9X` prefix = ecosystem/bridge layer (above core K9-AIF framework).

## Planned Adapters

| Class | Bridges | Target |
|---|---|---|
| `K9XLLMBridgeAdapter` | ABB base contract | All |
| `K9XLiteLLMBridgeAdapter` | CrewAI / LiteLLM interface | CrewAI 1.x |
| `K9XLangChainBridgeAdapter` | LangChain BaseLLM/BaseChatModel | LangChain 0.2+ |
| `K9XOpenAIBridgeAdapter` | OpenAI-compatible REST API | Any OpenAI-compat |
| `K9XAnthropicBridgeAdapter` | Anthropic SDK | Claude models |
| `K9XLLMBridgeFactory` | Config-driven provisioning | All of the above |

## Architecture

```
BaseK9XLLMBridge (ABB)
    → K9XLiteLLMBridgeAdapter   implements LiteLLM interface
    → K9XLangChainBridgeAdapter  implements BaseLanguageModel
    → K9XOpenAIBridgeAdapter     implements OpenAI chat completions
    → K9XAnthropicBridgeAdapter  implements Anthropic messages API
    → K9XBridgeFactory           create(config) → right adapter
```

Each adapter:
1. Accepts LLM call from the external framework (in that framework's format)
2. Translates to K9-AIF `InferenceRequest`
3. Routes through `llm_invoke()` → K9ModelRouter → OllamaLLM / provider
4. Returns response in the external framework's expected format

## Integration Point (DoW / CrewAI example)

```python
# In crew_loader_k9x.py (new loader)
from k9_aif_abb.k9_adapters.k9x.k9x_bridge_factory import K9XBridgeFactory

llm = K9XBridgeFactory.create(config)      # returns K9XLiteLLMBridgeAdapter
agent = Agent(role=..., goal=..., llm=llm) # CrewAI agent uses K9X bridge
```

When this is wired: every CrewAI LLM call is governed, routed, and audited
by K9-AIF — regardless of which model is selected or which provider serves it.

## Significance

- **For the framework**: completes the "AI motherboard" — universal LLM governance
- **For the book**: Chapter 6 (Factory + Adapter Patterns) — the motherboard metaphor
- **For the IEEE paper**: novel contribution — cross-framework LLM governance bus
- **For the DoW integration**: K9XLiteLLMBridgeAdapter closes the CrewAI governance gap

## Location in repo

```
k9_aif_abb/k9_adapters/k9x/
    __init__.py
    base_k9x_llm_bridge.py        ABB contract
    k9x_litellm_bridge_adapter.py CrewAI / LiteLLM
    k9x_langchain_bridge_adapter.py
    k9x_openai_bridge_adapter.py
    k9x_anthropic_bridge_adapter.py
    k9x_bridge_factory.py
```

## Status: Not started — next major framework milestone
