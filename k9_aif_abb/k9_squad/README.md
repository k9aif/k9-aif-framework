# k9_squad

A Squad is a team of agents that runs a capability as an ordered flow inside an orchestration.

- `BaseSquad`: the squad execution unit; runs its agents in the `flow` order from squad YAML,
  each agent enriching the shared context.
- `SquadContext`: shared state during squad execution.
- `SquadLoader`: builds squads from YAML (`load_one(path, squad_id)`), resolving agents by name
  from an `AgentRegistry`.
- `DefaultSquadMonitor`: observability for squad execution.
- `IntentSquad`: the out-of-the-box intent-classification squad used by `IntentOrchestrator`.
