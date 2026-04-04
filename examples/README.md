# Examples

This folder contains example applications and supporting diagrams built using the **K9-AIF Framework**.

These examples demonstrate how K9-AIF can be used to implement practical,
domain-oriented AI applications while preserving architectural structure,
modularity, and governance.

---

## What These Examples Show

- How to structure applications on top of K9-AIF
- How to compose **Squads, Agents, and Orchestrators**
- How to apply **model routing via ModelRouterFactory**
- How to integrate LLM capabilities into real-world workflows
- How to build reusable, extensible AI application patterns

---

## Folder Structure

### `k9chat/`

A lightweight chat example demonstrating:

- squad-driven execution
- model routing via **ModelRouterFactory** and the default **K9ModelRouter**
- browser and CLI interaction
- runtime metadata (provider, model, host)

---

### `acme_support_center/`

A support-oriented example demonstrating:

- squad-based orchestration
- multi-agent collaboration patterns
- customer support workflow structure
- modular service interaction using K9-AIF building blocks

---

### `acme_health_insurance/`

A domain-oriented example demonstrating:

- claims-related workflow structure
- document and intake-oriented processing patterns
- extensible enterprise AI solution design
- domain-aligned orchestration using K9-AIF concepts

---

### `diagrams/`

Supporting architectural diagrams for the examples, including:

- class diagrams
- runtime flow diagrams
- example-specific architecture visuals

Example:

```text
examples/diagrams/k9-chat-class-diagram.png

```
