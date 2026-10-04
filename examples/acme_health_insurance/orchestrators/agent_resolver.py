# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Create an agent by name from the application's config (``agents:`` map name -> module).

Orchestrators reference agents by name only, the same way AcmeOrchestrator loads
domain orchestrators from orchestrators.yaml (three-layer decoupling: no agent
class is imported in an orchestrator module).
"""

import importlib
from typing import Any, Dict


def create_agent(config: Dict[str, Any], name: str, **kwargs: Any):
    module = (config.get("agents") or {}).get(name)
    if not module:
        raise KeyError(f"agent {name!r} is not listed under 'agents:' in config.yaml")
    cls = getattr(importlib.import_module(module), name)
    return cls(config=config, **kwargs)
