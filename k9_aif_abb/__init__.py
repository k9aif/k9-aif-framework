# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
All rights reserved.

K9-AIF - Agent-based Integration Framework
-------------------------------------------
K9-AIF is a governed, modular, and extensible enterprise framework for
agentic automation and intelligent orchestration.  

It provides a unified abstraction layer that transforms Architecture
Building Blocks (ABBs) into operational Solution Building Blocks (SBBs)
through configuration-driven governance, monitoring, and persistence.

**Key Design Principles**
- Governed orchestration aligned to TOGAF ADM phases  
- Layered ABB->SBB architecture: Core, Agents, Factories, Orchestrators  
- Extensible persistence, messaging, and monitoring back-ends  
- Interoperability with CrewAI, MCP servers, and external LLM providers  
- Built-in security, auditability, and policy enforcement hooks  

**Framework Extensibility**
K9-AIF is architected to support multiple enterprise architecture
methodologies. While the current reference implementation aligns with
**TOGAF**, it can be readily specialized for **DoDAF**, forming the
foundation for the forthcoming **K9-AIF-DoDAF** variant intended for
federal systems engineering automation and compliance.

**Primary Packages**
- `k9_core` - base ABB classes for all framework layers  
- `k9_agents` - governed SBB implementations (Chat, Persistence, Security, etc.)  
- `k9_factories` - dynamic factories for orchestration, persistence, and connectors  
- `k9_monitoring` - observability and telemetry adapters  
- `k9_persistence` - durable and vector storage back-ends  
- `k9_orchestrators` - high-level control and routing flows  
- `k9_utils` - configuration, timing, and transformation utilities  

This package forms the foundation for all K9-AIF applications, including
CrewAI-integrated proofs of concept and future DoDAF-aligned automation
prototypes for enterprise and government use.

---

** K9-AIF Framework Structure**

| Package | Layer | Description |
|----------|--------|-------------|
| `k9_core` | ABB (Base Layer) | Defines base abstract classes and interfaces - agents, orchestration, persistence, governance, security, etc. |
| `k9_agents` | SBB (Implementation Layer) | Concrete, governed implementations of ABBs (ChatAgent, GovernanceAgent, PersistenceAgent, etc.). |
| `k9_factories` | Integration Layer | Factory classes for orchestration, persistence, monitoring, and LLM connectors. |
| `k9_monitoring` | Observability Layer | Adapters for Grafana, Prometheus, CloudWatch, and OpenTelemetry metrics. |
| `k9_persistence` | Data Layer | Concrete persistence back-ends (SQLite, ChromaDB, etc.). |
| `k9_orchestrators` | Control Layer | Domain-specific orchestrators coordinating multiple ABB/SBBs. |
| `k9_utils` | Utility Layer | Config loader, logging setup, timer utilities, and XML/JSON transformers. |
| `policies` | Governance Config | YAML policies defining governance, security, and compliance rules. |
| `tests` | Verification Layer | Unit and integration tests ensuring ABB/SBB contract compliance. |

---

**Usage Example**
```python
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.persistence_factory import PersistenceFactory

agent = BaseAgent()
store = PersistenceFactory.create({"persistence": {"backend": "sqlite"}})
"""