# Developer steps for this acme_support_center

`acme-support-center.png`: architecture diagram (Router → SupportOrchestrator → support_squad →
Triage, Knowledge, Resolution and Quality agents), used by `../../README.md`.

## Step 1: Scaffold

Scaffold via K9X Studio (k9x-ecosystem/k9x_studio) -- drag-and-drop canvas -> Generate Scaffold.

## Step 2: Customize

Give each agent its behavior in its YAML under `agents/yaml/` (role, goal, instructions, and the
`pattern`: react, agentic_rag, plan_execute or reflection) and order the agents in the squad flow (`config/squads.yaml`).
Keep the `security.shield` profile in `config/config.yaml` so every agent runs governed.

## Step 3: Build and run

From the repository root: `./run_acme_support_center.sh`. Check conformance with
`k9aif inspect examples/acme_support_center`.
