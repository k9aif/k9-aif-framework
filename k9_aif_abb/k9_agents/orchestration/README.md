# k9_agents/orchestration

Placeholder package (only `__init__.py`). Concrete orchestrators live in
`k9_aif_abb/k9_orchestrators/`; the contract is `BaseOrchestrator` in
`k9_aif_abb/k9_core/orchestration/base_orchestrator.py`.

## Writing an orchestrator

```python
from typing import Any, Dict
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator


class MyOrchestrator(BaseOrchestrator):
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("[%s] start", self.__class__.__name__)
        results = self.execute_squads([self.my_squad], payload)   # Orchestrator -> Squads only
        return {"status": "completed", **results}
```

Register it with a router by intent:

```python
router.register_orchestrator("myflow", MyOrchestrator(config=config))
```

Or declare it in `config/orchestrators.yaml` (`name`, `module`, `intent`). An orchestrator
references squads only, never agent classes (three-layer decoupling; `k9aif inspect` rule
K9-DEC-001).
