---
description: Inspect K9-AIF SBB code for architectural compliance and produce recommendations. Checks decoupling rules, ABB contract adherence, governance, LLM invocation patterns, and config hygiene.
---
**Before doing anything else, check that `/k9aif:configure` has been run.**
If `K9AIF_PROJECT_ROOT` and `K9AIF_APP_NAME` are not set, refuse and say:
> "Please run `/k9aif:configure` first to set your project root and app name."
Do not proceed until init has been run.



# K9-AIF: Inspect (k9_code_review)

Review K9-AIF Solution Building Block (SBB) code for architectural compliance against ABB contracts.

**First: check `$ARGUMENTS`. If empty, ask the user before doing anything else:**
> "Which folder would you like to inspect? (e.g. `examples/MyApp`, `k9_projects/MyApp`, or a subfolder like `examples/MyApp/agents`)"
> Do not proceed until the user provides a path.

The user specifies the SBB folder to inspect via `$ARGUMENTS`. Accepted forms:
- App name: `EOC` → resolves to `examples/K9X_Enterprise_Insurance_OperationsCenter/`
- Relative path: `examples/MyApp/`
- Absolute path: `/Users/ravinatarajan/ai/k9-aif-framework/examples/MyApp/`
- Subfolder: `examples/MyApp/agents/` — inspect only agents in that app

**Default: inspect SBBs only.**
- Primary targets: `examples/<AppName>/` and `k9_projects/<AppName>/`
- If the user explicitly passes a path inside `k9_aif_abb/`, inspect it — some organizations extend or customize the ABB layer and need to verify their changes are consistent with the ABB contracts.
- If the user passes `k9_aif_abb/` without a subfolder (the entire ABB), ask for confirmation: "You are about to inspect the full ABB layer. Are you sure? This is usually only needed if your organization has modified the framework core."

## What to check

### 1. Three-layer decoupling violations
- Agent imports or references a Squad class → violation
- Squad YAML contains an `orchestrator:` field → violation
- Agent YAML contains a `squad:` or `routing:` field → violation
- Orchestrator references another orchestrator by name directly (not via registry) → warning

### 2. LLM invocation pattern
- Agent calls `OllamaLLM` directly → violation (must use `llm_invoke`)
- Agent calls `LLMFactory.get()` directly → violation (must use `llm_invoke`)
- Agent calls `llm_invoke` without wrapping in try/except RuntimeError → warning
- `InferenceRequest` built without `task_type` → warning (model scoring degraded)

### 3. ABB contract adherence
- Agent class does not extend `BaseAgent` or a recognised K9-AIF base class → violation
- `K9ValidationLoopAgent` subclass missing `finalize()` override → violation
- `K9ValidationLoopAgent` subclass defines `execute()` instead of the five loop methods → violation
- Flow step in squad YAML is a plain string, not a dict with `agent:` key → violation (raises ValueError at runtime)

### 4. Governance
- Agent's `execute()` does not call `enforce_governance()` and YAML has `governance.pre_process: true` → warning
- `NoopGovernance` imported or instantiated in non-test code → warning
- `K9_ENV` not set in the deployment config → warning

### 5. Config hygiene
- Hardcoded Ollama URL, model name, or IP address in agent Python code → violation (must come from config)
- Credentials or API keys present in any `config.yaml` → violation
- Agent YAML `model:` value not present in `inference.model_catalog` in `config.yaml` → warning

### 6. Squad YAML structure
- `squads:` top-level wrapper missing (squad ID is not a key under `squads:`) → violation
- Agent listed in `agents:` but absent from `flow:` → warning (dead agent)
- Agent in `flow:` but not listed in `agents:` → violation

### 7. Pattern fitness recommendation
- Agent has an internal loop (while/for) inside `execute()` that re-calls `llm_invoke` → recommend migrating to `K9ValidationLoopAgent`
- Agent accumulates results across iterations into a list inside `execute()` → same recommendation

## Output format

Produce a structured report:

```
K9-AIF Inspect — <AppName>
==========================

VIOLATIONS (must fix — will break at runtime or in production):
  [AGENT]  ClaimsAgent: calls LLMFactory.get() directly — use llm_invoke instead
  [SQUAD]  ClaimsSquad: flow step "AuditAgent" is a plain string — must be {agent: AuditAgent}

WARNINGS (should fix — degrades reliability or governance):
  [AGENT]  FraudAgent: llm_invoke not wrapped in try/except RuntimeError
  [CONFIG] config.yaml: model alias "fast" not found in inference.model_catalog

RECOMMENDATIONS (long-term improvements):
  [PATTERN] FraudAgent: internal retry loop detected inside execute() — consider K9ValidationLoopAgent

Summary: 2 violations, 2 warnings, 1 recommendation.
```

Severity levels: **VIOLATION** (fix before production) · **WARNING** (fix soon) · **RECOMMENDATION** (long-term).
