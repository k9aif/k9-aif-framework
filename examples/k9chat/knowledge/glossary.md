# K9-AIF Glossary

Short, precise definitions of core K9-AIF/K9X terms — deliberately dense
and one-term-per-paragraph, unlike the longer prose docs elsewhere in this
knowledge base. Semantic search over long-form README/blog text tends to
favor broader passages over a single definitional sentence buried inside
them; this file exists specifically to be the best match for direct "what
is X" / "what does X stand for" questions.

## ABB (Architecture Building Block)

ABB stands for **Architecture Building Block**. An ABB is an abstract
contract defined in `k9_core/` — it specifies an interface, a lifecycle,
and governance hooks, but contains no domain-specific logic. Examples:
`BaseAgent`, `BaseOrchestrator`, `BaseRouter`, `BaseSquad`. ABBs are rarely
touched directly; new capability extends one, never edits one.

## SBB (Solution Building Block)

SBB stands for **Solution Building Block**. An SBB is a concrete
implementation that extends an ABB contract, adding real domain logic,
technology choices, and runtime integrations. SBBs live in `examples/<App>/`
or `k9_projects/<App>/`, never inside the framework's own `k9_core/`.

## Router

The entry point of a K9-AIF pipeline (`K9EventRouter` / `BaseRouter`).
Receives an event, maps known `event_type`s to a domain topic, and hands
unknown ones to an `IntentOrchestrator`. A Router knows about
Orchestrators only — never Squads or Agents directly (three-layer
decoupling).

## Orchestrator

Coordinates one or more Squads for a domain workflow (`BaseOrchestrator`).
Receives work from a domain topic, runs Squads sequentially or in
parallel via `execute_squads()`, and owns Kafka publishing for results/
downstream topics. An Orchestrator knows about Squads only — never Agents
directly.

## Squad

A sequential flow of Agents defined in YAML (`BaseSquad`, loaded via
`SquadLoader`). A Squad has no `orchestrator:` field in its own config —
it doesn't know which Orchestrator uses it, preserving the one-directional
layer decoupling.

## Agent

The unit that actually calls an LLM (`BaseAgent`). Every agent gets a
governance pipeline via `require_governance()`. Three common patterns:
`BaseAgent` (one-shot answer), `K9ValidationLoopAgent` (iterative
convergence on a confidence score), `K9PlanningLoopAgent` (agent plans
and revises its own steps).

## k9x_Shield

The framework's deterministic pattern-matching security layer
(`k9_security/vulnerability/`) — 13 concrete `BaseVulnerabilityCheck`
subclasses (PromptInjectionCheck, PIIBoundaryCheck, HardcodedCredentialCheck,
and others), run in order by `VulnerabilityChain`, wrapped by
`ShieldGovernance`. A BLOCK-status check raises `PermissionError`.

## Zero Trust (Zero Trust Execution Layer)

A separate, identity/risk-based security mechanism (`k9_security/zero_trust/`),
distinct from k9x_Shield's pattern-matching. Lives on `BaseOrchestrator`
only, via `apply_zero_trust()`: compromise check → role-based
authorization → data-loss/masking → risk scoring → `TrustDecision`. Off
by default (`enable_zero_trust: false`); additive to k9x_Shield, not a
replacement for it.

## Model Router / K9ModelRouter

Selects which configured model alias handles a given `InferenceRequest`
via weighted scoring against a model catalog (capabilities, latency
budget, cost profile), then dispatches to the concrete `BaseLLM` adapter
for that alias (e.g. `OllamaLLM`).

## K9-AIF (the framework's own name)

K9-AIF stands for an architecture-first framework for building governed,
observable, multi-agent AI systems, grounded in OOA/OOD/TOGAF discipline
rather than an ad-hoc collection of agent scripts. Its own stated
positioning: "Not just agents. Architecture."
