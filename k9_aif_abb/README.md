# K9-AIF Framework

**pip package:** `k9_aif_framework` — **import namespace:** `k9_aif_abb`

The pip package is named `k9_aif_framework` to communicate what it is — a framework.  
The framework code lives in the `k9_aif_abb` module — ABB stands for **Architecture Building Blocks**,  
reflecting that this is the architectural foundation other solutions are built upon, not an application itself.

```bash
pip install k9_aif_framework        # install the framework
```

```python
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent   # import from k9_aif_abb
```

K9-AIF provides a modular, governed architecture for building  
**agentic AI applications using composable architectural building blocks.**

The framework separates **architectural abstractions (ABB)** from  
**solution implementations (SBB)**, enabling flexible and extensible  
multi-agent AI systems.

---

## Purpose

The `k9_aif_abb` package implements the reusable components that form the
foundation of K9-AIF applications.

These components provide standardized contracts for:

- agent behavior
- orchestration
- routing
- inference
- messaging
- persistence
- governance
- monitoring
- storage
- integrations

Applications can compose these building blocks to create governed,
configurable AI systems.

---

## Package Structure

``` code

k9_aif_abb/
│
├── k9_core
│   Core framework abstractions and base classes
│
├── k9_agents
│   Implementations of agents for orchestration, messaging,
│   enrichment, security, storage, and integrations
│
├── k9_orchestrators
│   Orchestrator implementations coordinating multi-agent workflows
│
├── k9_factories
│   Factory classes for dynamically constructing framework components
│
├── k9_monitoring
│   Monitoring infrastructure and observability integrations
│
├── k9_persistence
│   Persistence layer implementations (SQLite, vector DB, etc.)
│
├── k9_storage
│   Storage abstractions for files, databases, and object storage
│
├── k9_data
│   Data adapters and vector database integrations
│
├── k9_utils
│   Utility modules supporting configuration, logging, and helpers
│
├── k9_governance
│   Governance policies and rule enforcement mechanisms
│
├── k9_mcp
│   MCP-based service integration and inference servers
│
├── config
│   Configuration files defining flows, governance policies,
│   orchestrators, and tools
│
└── policies
Governance policy definitions
```

---

## Architectural Principles

The K9-AIF framework is built around several architectural principles:

## Architectural Principles

The K9-AIF framework is built around the following architectural principles:

1. **Separation of Architecture and Implementation (ABB vs SBB)**  
   Architecture Building Blocks (ABB) define stable architectural capabilities and interfaces,  
   while Solution Building Blocks (SBB) provide concrete implementations.

2. **Configuration-Driven Architecture**  
   Application flows, orchestrators, and governance policies can be defined through configuration
   rather than hard-coded logic, enabling flexible system composition.

3. **Composable Multi-Agent Architecture**  
   AI systems are constructed by composing specialized agents coordinated by orchestrators,
   allowing modular and scalable agent workflows.

4. **Governed AI Systems**  
   Governance policies can be applied across agent workflows to support compliance,
   safety, and responsible AI behavior.

5. **Extensible Integration Layer**  
   External services, LLM providers, and tools are integrated through adapter-based
   connectors, enabling provider-independent architectures.

6. **Observability and Monitoring**  
   Built-in monitoring and telemetry components allow systems to track agent activity,
   workflow execution, and operational metrics.

7. **Pluggable Infrastructure Components**  
   Persistence, storage, messaging, and streaming systems can be replaced or extended
   without modifying the core framework.

---

## Installation

### From PyPI (once published)

```bash
pip install k9_aif_framework
```

### Local install (development)

```bash
# Standard install from local source
pip install /path/to/k9-aif-framework/k9_aif_abb

# Editable install — changes to the ABB are reflected immediately (recommended for development)
pip install -e /path/to/k9-aif-framework/k9_aif_abb
```

### Verify installation

```python
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
print("k9_aif_framework installed successfully")
```

> **Note:** The pip package name is `k9_aif_framework`. The Python import namespace remains `k9_aif_abb`.
> ```python
> # pip install k9_aif_framework
> from k9_aif_abb.k9_core.agent.base_agent import BaseAgent   # import path unchanged
> ```

### Inspect your solution

A dedicated architectural conformance inspector (`k9x_inspector`) is in active development in [k9x-ecosystem](https://github.com/k9aif/k9x-ecosystem). An earlier, naive per-file version of this check shipped inside the framework itself but produced false positives on legitimate code (it didn't resolve inheritance chains) and has been removed.

---

## Author's Recommendation

### 1. Know the Framework

Before building, understand the architecture. K9-AIF is built on a strict **ABB/SBB separation** —
Architecture Building Blocks define the contracts, Solution Building Blocks implement the domain.
Read `CLAUDE.md` for architecture and `SKILLS.md` for step-by-step recipes. These are the two
documents that will make you productive fast.

### 2. Use Claude Code with VS Code — the Recommended Path

The most effective way to build with K9-AIF is **Claude Code** inside **VS Code**.

K9-AIF ships with `CLAUDE.md` and `SKILLS.md` — these are loaded automatically by Claude Code,
giving it a deep understanding of the framework's architecture, conventions, and code generation
rules. Claude Code will generate agents, squads, orchestrators, and config that comply with the
framework out of the box, without you having to explain the patterns each time.

Download and install Claude Code from:
**https://claude.ai/code**

It is available as a VS Code extension, a desktop app, and a CLI.
Once installed, open your solution folder in VS Code and Claude Code is ready to use.

Claude Code understands:
- ABB contracts and how to extend them correctly
- Squad YAML format, agent registration, flow structure
- Kafka ownership (Router publishes, Orchestrator consumes)
- Governance enforcement patterns
- The full inference pipeline through `llm_invoke`

### 3. No Claude Code? Use K9X Studio

If you are not using Claude Code, use **K9X Studio** (k9x-ecosystem/k9x_studio) -- drag-and-drop canvas → Generate Scaffold -- to create a compliant solution stub.

See "Inspect your solution" above for validating it once built.

---

**Happy Coding!**

Building Architecture-First Agentic Applications — done right, that really works.

*— Ravi Natarajan, k9x.ai*
