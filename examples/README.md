# Examples

This folder contains example applications built using the **K9-AIF Framework**.

These examples demonstrate how K9-AIF can be used to implement practical,
domain-oriented AI applications while preserving architectural structure,
modularity, and governance.

---

## What These Examples Show

- How to structure applications on top of K9-AIF
- How to compose **Squads, Agents, and Orchestrators**
- How to apply **model routing via ModelRouterFactory**
- How to integrate LLM capabilities into real-world workflows
- How to build reusable, extensible AI application patterns

---

## Available Examples

| Example | What it shows |
|---|---|
| [K9X_Enterprise_Insurance_OperationsCenter](K9X_Enterprise_Insurance_OperationsCenter/README.md) | The canonical example: Kafka router, per-domain orchestrators, squads of validation-loop agents, HIL escalation, custom model router, governance by construction |
| [acme_support_center](acme_support_center/README.md) | A support squad (triage, knowledge, resolution, quality) with different agent patterns; the bundled Quick Start demo |
| [acme_health_insurance](acme_health_insurance/README.md) | Claims workflow with eligibility and provider lookup, served by a FastAPI backend and web UI |
| [rfp_analyzer](rfp_analyzer/README.md) | Document ingestion, RAG retrieval and governed analysis |
| [weather_assist](weather_assist/README.md) | A CrewAI crew governed through the K9-AIF CrewAI adapter |
| [weatherAssistLang](weatherAssistLang/README.md) | The same idea with LangGraph |
| [zero_trust_execution_demo](zero_trust_execution_demo/README.md) | Signed identity at the Router edge; API-key and Keycloak (OIDC) authentication |
| `k9routing` | Intent routing: deterministic and intent-based routing, OOB and SBB overrides; in-memory, no Kafka or LLM (`python examples/k9routing/run.py`) |
| `prompt_evaluation` | Prompt evaluation pattern (test client: `test_prompt_evaluator.py`) |
| `myapp` | Minimal scaffold: one agent and its tests |

K9Chat, a chat application on `BaseAgent` and `llm_invoke`, lives in its own repository:
[k9aif/examples](https://github.com/k9aif/examples).

The EOC, ACME Support Center, ACME Health Insurance, RFP Analyzer and both Weather Assist examples
ship a `security.shield` profile in their `config.yaml`, so every agent runs under governance by
construction (k9-aif 1.15). In production (`K9_ENV` unset or `production`) an agent without
governance refuses to run.
