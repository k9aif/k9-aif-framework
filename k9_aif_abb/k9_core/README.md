# k9_core (ABBs)

Core abstract contracts used across K9-AIF. Agents, orchestrators and routers in a solution
extend these base classes; add a new contract here only for a cross-framework abstraction.

## Base classes

- `BaseAgent` (`agent/base_agent.py`): `execute(payload) -> dict`, and `execute_stream()`. Both are
  wrapped with governance when a subclass is defined (governance by construction).
- `BaseOrchestrator` (`orchestration/base_orchestrator.py`): `execute_flow(payload) -> dict`;
  runs squads, applies Shield and opt-in Zero Trust at its boundary, and provides
  `handle_requires_hil()` for a solution's `execute_flow()` to call when it catches `RequiresHIL`.
- `BaseRouter` (`router/base_router.py`): `route(payload) -> dict`,
  `register_orchestrator(intent, orchestrator)`.

## Subpackages

`agent`, `orchestration` (including `RequiresHIL` and `BaseHILOrchestrator`), `router`,
`governance` (pipeline, `governance_from_config`, call context), `inference` (provider adapters
and registry), `security`, `session`, `storage`, `persistence`, `messaging`, `streaming`,
`streams`, `cache`, `monitoring`, `logging`, `retrieval`, `evaluation`, `formatter`,
`presentation`, `integration`, `iot`, `supporting`.

## Logging

Base classes create the logger; components log through it:

```python
self.logger = logging.getLogger(self.__class__.__name__)   # set by the base class
self.logger.info("...")
```
