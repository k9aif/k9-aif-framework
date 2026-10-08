# Examples

This section contains example applications built using the **K9-AIF Framework**.

These examples demonstrate how K9-AIF can be used to implement practical, domain-oriented AI applications while preserving architectural structure, modularity, and governance.

The examples illustrate:

- how to structure applications on top of K9-AIF
- how to compose squads, agents, and orchestrators
- how to integrate LLM capabilities into real-world workflows
- how to apply framework patterns across different domains

---

## Available Examples

### K9X Enterprise Insurance Operations Center (EOC)
The canonical example: three processes (app, Kafka router, orchestrator), per-domain
orchestrators, squads of validation-loop agents, HIL escalation and a custom model router.

### ACME Support Center
A support-oriented example showing how K9-AIF can be used to structure customer-facing service workflows and agent collaboration patterns.

### ACME Health Insurance Claims
A domain-oriented example demonstrating how K9-AIF can support claims-related workflows, structured processing, and extensible enterprise AI solution patterns.

### More examples in the repository
`weather_assist` (a CrewAI crew governed through the CrewAI adapter), `weatherAssistLang`
(LangGraph), `rfp_analyzer`, `zero_trust_execution_demo`, `k9routing` and `prompt_evaluation`,
all under [`examples/`](https://github.com/k9aif/k9-aif-framework/tree/main/examples).

### K9Chat
A chat application on `BaseAgent` and `llm_invoke`; it lives in its own repository,
[k9aif/examples](https://github.com/k9aif/examples).

---

## Purpose

These examples are intentionally practical.

They are not intended to be production products out of the box.  
They exist to demonstrate how K9-AIF can be used as an architecture-first framework for building modular, governed, and extensible AI applications.
