# K9-AIF — K9 Agentic Integration Framework

K9-AIF is a modular architecture framework for building governed
enterprise-scale multi-agent AI systems.

The framework separates Architecture Building Blocks (ABB) from
Solution Building Blocks (SBB), enabling extensible and composable
agentic applications.

![K9-AIF Architecture](docs/diagrams/k9-aif-architecture.png)

K9-AIF provides architectural patterns for constructing agentic
workflows where multiple AI agents collaborate to perform reasoning,
analysis, and decision-support tasks while maintaining clear
governance, orchestration, and integration boundaries.

The framework draws inspiration from established architectural
disciplines, including:

- Object-Oriented Analysis & Design (OOA/OOD)
- Enterprise Architecture (TOGAF)
- Service-Oriented Architecture (SOA)
- Modern multi-agent AI systems

The goal is to enable **composable, scalable, and governed agentic AI applications**.

---

# Core Architectural Concepts

K9-AIF introduces two primary architectural abstractions.

## Architecture Building Blocks (ABB)

Architecture Building Blocks define abstract architectural capabilities and contracts within the K9-AIF framework. ABBs specify responsibilities, interfaces, and interaction patterns without prescribing concrete implementations or technologies.

An ABB typically defines:

- Interfaces and interaction contracts
- Responsibilities and functional boundaries
- Lifecycle expectations
- Governance and observability hooks

Examples include:

- Agent interface contracts
- Orchestrator contracts
- Tool connector interfaces
- Inference adapters
- Storage or persistence adapters

---

## Solution Building Blocks (SBB)

Solution Building Blocks provide concrete implementations of ABB contracts. SBBs introduce domain-specific behavior, technology choices, and runtime integrations while conforming to the architectural constraints defined by the ABB layer.

This separation allows architectural stability while enabling domain-specific extensions without modifying the core framework.

Examples:

- Document Analysis Agent
- Retrieval Agent
- CrewAI Agent
- LangChain Tool Adapter
- OpenAI LLM Connector

---

## Architectural Layers

A typical K9-AIF system is organized into a set of architectural layers that separate interface concerns, orchestration, external integration, inference, and persistence.

### Presentation Layer
Handles incoming user or system interactions through web interfaces, conversational channels, or APIs.

### Application Layer
Coordinates orchestration flows, routing, and workflow execution across agents and services.

### Integration Layer
Provides governed access to external systems, APIs, tools, messaging platforms, and storage services.

### Inference Layer
Supports model invocation, retrieval-augmented generation (RAG), and context-aware reasoning.

### Data Layer
Provides persistence, object storage, and messaging infrastructure used by the framework.

### Cross-Cutting Concerns
Security, governance, and observability apply across all layers to enforce policy, auditability, monitoring, and operational control.

---

## Prototype Implementations

Prototype systems based on K9-AIF demonstrate how the framework can support
governed multi-agent architectures across multiple domains.

Example demonstration systems include:

- **ACME Health Insurance Claims Assistant**  
  Multi-agent insurance workflow demo including eligibility checks,
  provider lookup, and claims support.  
  → [examples/acme-health-insurance](examples/acme-health-insurance)

- **WeatherAssist Decision Support System**

- **Sports Car Experience Center**

- **Department of War (DoW) Systems Engineering Pipeline**  
  Demonstrates how K9-AIF architectural patterns can automate multi-stage
  systems engineering workflows aligned with the **DoDAF 2.0 architecture
  framework**, exploring agent orchestration across multiple architectural
  stages using K9-AIF patterns together with the CrewAI orchestration framework.

---
  
---

## Design Goals

K9-AIF is designed to support the development of governed, composable agentic AI systems aligned with enterprise architecture practices.

Key architectural goals include:

- Modular architecture supporting independently deployable AI capabilities
- Composable intelligence through reusable architectural building blocks
- Governed AI workflows with policy and control integration
- Clear orchestration boundaries between agents, tools, and services
- Scalable integration with enterprise systems and external platforms

The framework bridges traditional **enterprise architecture principles** with emerging **agentic AI system design**.

---

## Example Use Cases

K9-AIF can be applied to enterprise AI systems that require governed orchestration of multiple AI capabilities.

Examples include:

- Enterprise architecture and technology landscape analysis
- Document intelligence and large-scale document processing
- Insurance claims analysis and decision support
- Automated systems engineering workflows
- Knowledge synthesis and research assistance

---

# Stub Generator

K9-AIF includes a lightweight **project stub generator** that bootstraps new agentic applications following the framework architecture.

The generator creates a ready-to-run project structure including:

- agents
- orchestrators
- configuration files
- workflow definitions
- test scaffolding

Example usage:

``` bash

=== K9-AIF Generator v0.1.0 ===

K9-AIF Generator CLI

Usage:
  ./k9_generator.sh preview <AppName>
  ./k9_generator.sh run <AppName>
  ./k9_generator.sh recycle <AppName>

Examples:
  ./k9_generator.sh preview WeatherAssist
  ./k9_generator.sh run ACMEInsurance
  ./k9_generator.sh recycle PetStore
```

---

## K9-AIF Developer Journey

![K9-AIF Developer Journey](images/developers_journey.png)

The diagram illustrates how applications are built using K9-AIF:

• **Architects** define reusable Architectural Building Blocks (ABB).  
• **Application developers** extend these ABBs into Solution Building Blocks (SBB).  
• **Business analysts** configure workflows and governance policies using YAML configuration without modifying code.

This layered approach separates architecture, implementation, and configuration,
allowing applications to evolve with minimal code changes.

---

## Project Status

K9-AIF is an actively evolving framework. The repository contains reference
architecture material, prototype implementations, and example applications
used to explore practical approaches to building governed agentic AI systems.

---

## License

This repository is released under the MIT License.

The framework concepts may be used, adapted, and extended for research and
development of agentic AI systems.

---

## Contributions

Contributions, discussions, and architectural ideas related to agentic AI
systems and multi-agent orchestration are welcome.

---

## Author

**Ravi Natarajan**  
AI Systems Architect  
Agentic AI • Multi-Agent Systems • LLM Applications  

Email: ravinatarajan@k9aif.com  
Website: https://k9aif.com

---

## Architectural Foundations

K9-AIF draws inspiration from established software architecture and enterprise architecture practices, including:

- Booch, G. *Object-Oriented Analysis and Design with Applications*
- Gamma, E., Helm, R., Johnson, R., Vlissides, J. *Design Patterns: Elements of Reusable Object-Oriented Software*
- The Open Group. *TOGAF Standard*

