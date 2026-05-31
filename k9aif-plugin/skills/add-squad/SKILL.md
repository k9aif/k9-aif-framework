---
description: Scaffold a new K9-AIF squad — creates the squad YAML with agents and flow steps. Pass the squad name, app name, and comma-separated agent names.
---
**Before doing anything else, check that `/k9aif:configure` has been run.**
If `K9AIF_PROJECT_ROOT` and `K9AIF_APP_NAME` are not set, refuse and say:
> "Please run `/k9aif:configure` first to set your project root and app name."
Do not proceed until init has been run.



# K9-AIF: Add Squad

Scaffold a new squad for the K9-AIF framework. The user provides: `<SquadName> <AppName> <Agent1,Agent2,...>` (e.g. `ClaimsSquad MyApp ClaimsTriageAgent,AdjudicationAgent,AuditAgent`).

## What to create

### Squad entry in `examples/<AppName>/config/squads.yaml`

Add under the `squads:` key (create the file if it does not exist):

```yaml
squads:
  <SquadName>:
    description: "<one sentence — what this squad does>"
    agents:
      - <Agent1>
      - <Agent2>
      - <AgentN>
    flow:
      - agent: <Agent1>
        result_key: <agent1_snake_case>
      - agent: <Agent2>
        result_key: <agent2_snake_case>
      - agent: <AgentN>
        result_key: <agentN_snake_case>
```

## Rules to follow
- `squads:` is the top-level wrapper — the squad ID is a key under it, not a `name:` field.
- Every flow step **must** be a dict with an `agent:` key — plain strings raise `ValueError` at runtime.
- Squad YAML has **no** `orchestrator:` field — the orchestrator is the caller; squads must not reference their caller.
- Agent YAML has **no** `squad:` or `routing:` fields — agents are squad-agnostic.
- `result_key` is the key under which each agent's result is stored in the shared execution context.
- After generating the YAML, remind the user to register all agents in `_load_squad()` and wire the squad with `SquadLoader`.

## Wire the squad in the orchestrator (show the user this pattern)

```python
from k9_aif_abb.k9_squad.squad_loader import SquadLoader

# Inside _load_squad() in the orchestrator:
loader = SquadLoader(agent_registry)
squad = loader.load_one(squads_yaml_path, "<SquadName>")
```
