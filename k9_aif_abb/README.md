# K9-AIF Framework

**pip package:** `k9-aif` — **import namespace:** `k9_aif_abb`

The pip package is `k9-aif` ([PyPI](https://pypi.org/project/k9-aif/)).  
The framework code lives in the `k9_aif_abb` module — ABB stands for **Architecture Building Blocks**,  
reflecting that this is the architectural foundation other solutions are built upon, not an application itself.

```bash
pip install k9-aif        # install the framework
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

```text
k9_aif_abb/
├── k9_core            ABB contracts: BaseAgent, BaseOrchestrator, BaseRouter, governance,
│                      inference, sessions, streaming, HIL signal
├── k9_agents          OOB agents: loop agents (validation, planning, critic-actor), intent,
│                      router, messaging, enrichment, security, supporting; AgentLoader, registry
├── k9_squad           SquadLoader, BaseSquad, IntentSquad
├── k9_orchestrators   OOB orchestrators (intent, governance, diagnostic, live agent),
│                      orchestrator loader and registry
├── k9_adapters        CrewAI, LangGraph and Claude Agent SDK adapters
├── k9_inference       K9 Model Router, model catalog, learned routing
├── k9_factories       factories: LLM, model router, storage, cache, sessions, monitors,
│                      authenticators, MCP connections, and more
├── k9_security        k9x_Shield vulnerability checks (ShieldGovernance), Zero Trust,
│                      identity, tool-result guard, security capability catalog
├── k9_governance      Guardian, chained and profanity governance
├── k9_inspect         static conformance inspection (28 rules; `k9aif inspect <folder>`)
├── k9_mcp             MCP client connectors and server ABBs
├── k9_data            vector DB adapters, embedding, retrieval
├── k9_storage         file, database and object storage; RoutingStateStore
├── k9_persistence     SQLite persistence
├── k9_sessions        session stores: in-memory, SQLite, Redis
├── k9_cache           cache adapters
├── k9_streams         in-memory and Kafka streams
├── k9_monitoring      console, Prometheus, OpenTelemetry, CloudWatch monitors; Grafana dashboard
├── k9_utils           llm_invoke (the single model-call path), config, logging helpers
├── config             framework default configuration (flows, governance, orchestrators, tools)
├── policies           governance policy definitions
├── db                 database schema
├── webui              minimal web UI
├── cli.py             the `k9aif` command
└── tests              framework test suite (pytest)
```

---

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

4. **Governance by Construction**  
   Every `BaseAgent` subclass's `execute()` and `execute_stream()` are wrapped with governance
   when the class is defined, and `llm_invoke()` checks any model call made outside an agent.
   Setting `security.shield.enabled: true` (with check lists) in a solution's config gives every
   agent `ShieldGovernance`; in production (`K9_ENV` unset or `production`) an agent with no
   governance configured refuses to run.

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

### From PyPI

```bash
pip install k9-aif
```

### Local install (development)

```bash
# Standard install from local source (the repository root holds pyproject.toml)
pip install /path/to/k9-aif-framework

# Editable install — changes to the ABB are reflected immediately (recommended for development)
pip install -e /path/to/k9-aif-framework

# Optional extras, e.g. Kafka and PostgreSQL, or everything
pip install "k9-aif[kafka,postgres]"
pip install "k9-aif[all]"
```

### Verify installation

```python
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
print("k9-aif installed successfully")
```

> **Note:** The pip package name is `k9-aif`. The Python import namespace is `k9_aif_abb`.
> ```python
> # pip install k9-aif
> from k9_aif_abb.k9_core.agent.base_agent import BaseAgent   # import path unchanged
> ```

### Inspect your solution

`k9_inspect` checks a solution statically (Python AST and YAML; nothing is imported or run)
against 28 conformance rules: ABB contracts, three-layer decoupling, the single model path
(`llm_invoke`), Kafka ownership, governance by construction, secrets, private IPs, and
squad/agent YAML.

```bash
k9aif inspect /path/to/your-solution                 # report in the terminal
k9aif inspect . --markdown report.md --json          # also write Markdown, print JSON
k9aif inspect . --fail-on violation                  # exit 1 at or above a severity (for CI)
```

Organisations add their own rules with `InspectionRuleRegistry.register()`. The
[K9X Inspector](https://github.com/k9aif/k9x-inspector) web front end runs the same rules on
every push.

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
- Governance by construction (`security.shield` in config)
- The full inference pipeline through `llm_invoke`

### 3. No Claude Code? Use K9X Studio

If you are not using Claude Code, use **K9X Studio** (k9x-ecosystem/k9x_studio) -- drag-and-drop canvas → Generate Scaffold -- to create a compliant solution stub.

See "Inspect your solution" above for validating it once built.

---

**Happy Coding!**

Building Architecture-First Agentic Applications — done right, that really works.

*— Ravi Natarajan, k9x.ai*
