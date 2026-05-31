---
description: Scaffold a custom K9-AIF model router by extending BaseModelRouter. Pass the router name and app name.
---
**Before doing anything else, check that `/k9aif:configure` has been run.**
If `K9AIF_PROJECT_ROOT` and `K9AIF_APP_NAME` are not set, refuse and say:
> "Please run `/k9aif:configure` first to set your project root and app name."
Do not proceed until init has been run.



# K9-AIF: Add Router

Scaffold a custom model router that replaces `K9ModelRouter`. Use this when a solution needs custom routing logic — cost optimisation, compliance routing, A/B testing, or provider switching.

The user provides: `<RouterName> <AppName>` (e.g. `ComplianceRouter MyApp`).

## When to use

Only create a custom router when `K9ModelRouter` is insufficient. If the catalog scoring (task_type, sensitivity, latency_budget, cost_profile) covers the use case, keep the OOB router and just update `config.yaml`.

## What to generate

### Python class — `examples/<AppName>/routers/<router_name_lower>.py`

```python
from k9_aif_abb.k9_inference.routers.base_model_router import BaseModelRouter
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.models.route_decision import RouteDecision


class <RouterName>(BaseModelRouter):

    def route(self, request: InferenceRequest) -> RouteDecision:
        # Custom routing logic — pick a model alias from the catalog
        alias = "reasoning" if request.task_type == "reasoning" else "general"
        return RouteDecision(model_alias=alias)

    def invoke(self, request: InferenceRequest):
        decision = self.route(request)
        llm = self._get_llm(decision.model_alias)
        return llm.invoke(request.prompt)
```

### Register in `config.yaml`

```yaml
inference:
  router:
    type: <router_name_lower>
    default_model: general
    persistence:
      enabled: true
      provider: sqlite
```

## Rules to follow
- Extend `BaseModelRouter`, not `K9ModelRouter`.
- `route()` must return a `RouteDecision` with a valid `model_alias` from the catalog.
- Use `self._get_llm(alias)` (inherited) to get the `OllamaLLM` instance — never instantiate LLMs directly.
- Register the router type string in config to match the class file name (convention, not enforced).
- Agents, squads, and orchestrators are unaffected by router substitution — routing is fully decoupled.
