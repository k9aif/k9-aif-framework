# Security policy

K9-AIF is a framework for governed agentic AI systems, so a weakness in it can become a weakness in every
application built on it. This file says how to report one, and how to configure K9-AIF securely. The second
part is written for people and for coding assistants alike.

## Reporting a vulnerability

Please report privately, not in a public issue.

1. Open the repository's **Security** tab and choose **Report a vulnerability**
   (GitHub private vulnerability reporting). Only the maintainer sees the report.
2. Include the k9-aif version, the configuration involved (for example which Shield checks are enabled), and
   the smallest input or code that reproduces the problem.
3. If the Report button isn't available, open a public issue that says only "security contact requested",
   with no details, and a private channel will be arranged.

What happens next:

- The report is acknowledged, normally within 7 days.
- Confirmed issues are fixed in a new release. The fix, and its test, land in the same commit, and the
  security capability catalog (`k9_aif_abb/k9_security/capabilities.yaml`) is updated with it.
- The advisory is published when the fixed release is on PyPI. Reporters are credited in the advisory and in
  `CHANGELOG.md`, unless they ask not to be.

### Supported versions

Fixes go into the latest release line. Upgrade to the latest `k9-aif` from PyPI to receive them.

| Version | Supported |
|---|---|
| Latest minor release (1.27.x today) | Yes |
| Earlier releases | No: upgrade |

### Scope

In scope: the framework package `k9_aif_abb` as published on PyPI (`pip install k9-aif`): governance
(k9x Shield, Granite Guardian integration, Zero Trust, identity), the tool gate, the model router and
`llm_invoke`, the orchestrator adapters (CrewAI, LangGraph, Claude Agent SDK, OpenAI Agents SDK), HIL
signalling, persistence and messaging.

Out of scope here: applications built on K9-AIF and the K9X ecosystem products (each has its own repository),
and weaknesses of a model itself that K9-AIF does not claim to control. The capability catalog lists the
known gaps; a report that one of them is still open is welcome but not new.

## Configuring K9-AIF securely

Several protections are off in the shipped configuration so that a new project runs anywhere. A production
deployment turns them on deliberately. Each item below names the setting and what it protects.

| Do this | Why |
|---|---|
| Run production with `K9_ENV=production` (unset means production) | Agents refuse to run without governance; Shield fails closed when a check errors |
| Enable k9x Shield: `security.shield.enabled: true` **with** the ingress and egress check lists | Shield is off in the framework's default config; enabled with no check lists it blocks nothing |
| Prove Shield is active with one prompt-injection test after deployment | A misconfigured chain still logs `enabled=True` |
| Enable Zero Trust (`enable_zero_trust`) with a role policy | It is off by default, and off means every call is allowed |
| Use signed identity: `security.identity.mode: signed` with `K9_IDENTITY_SECRET` set | The 1.x default reads roles from the payload, so a caller can claim any role |
| Enable the tool gate (`security.tool_gate.enabled: true`) where agents call tools with real effects | A tool call then runs only on values checked against records the model did not write |
| Keep secrets in `.env` or a secret manager, never in `config.yaml` or the repository | Configuration files are shared and committed |
| Pin `k9-aif` and your model versions in production | A change of either changes behaviour |

The full list of controls, each mapped to the OWASP Top 10 for LLM Applications and for Agentic
Applications, with its limits and the known gaps:
[`k9_aif_abb/k9_security/capabilities.yaml`](k9_aif_abb/k9_security/capabilities.yaml).

## Rules for code that uses K9-AIF (people and coding assistants)

These are enforced by tests, hooks or `k9aif inspect` where possible. The reasons are in
[`CLAUDE.md`](CLAUDE.md).

- **Models only through `llm_invoke()`** (or `llm_route()` for a runtime that makes the call itself). Never
  call an LLM client, `LLMFactory` or the model router directly: that skips governance, retries and tracing.
- **Never weaken governance to make something pass.** Don't use `NoopGovernance` outside development and
  tests, don't set `_governs_own_execute` in application code, and don't remove a Shield check without
  recording why. If a check blocks legitimate content (an attack write-up being analysed, for example),
  scope it for that agent and say so in the code.
- **Tool results are untrusted input.** Screen them (`screen_tool_result` / `@govern_tool_result`, or the
  adapters' tool guardrails) before a model reads them.
- **Failures propagate.** An agent never turns an error or a governance block into ordinary output; the
  orchestrator records it.
- **Only the Router and Orchestrators publish to Kafka.** An agent asks for a human decision by raising
  `RequiresHIL`.
- **No secrets, hardcoded IP addresses or personal data** in code, configuration or test fixtures.

Questions that aren't vulnerabilities are welcome on [forum.k9x.ai](https://forum.k9x.ai) or in Issues.
