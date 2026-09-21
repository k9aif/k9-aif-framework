# K9-AIF FAQ

Action-oriented "how do I..." questions — deliberately separate from
glossary.md (which defines *terms*, not *how to do things*). Heading-
chunked like glossary.md, one question per section, so a direct match
retrieves a complete, self-contained answer rather than a fragment of a
longer README.

## How do I get started building a solution with K9-AIF?

Two paths, not mutually exclusive. (1) **K9X Studio** — a browser-based
visual builder at [studio.k9x.ai](https://studio.k9x.ai), or run your own:
`pip install k9x` then `k9x studio` (opens at `http://localhost:12999` by
default). Drag-and-drop composition of agents/squads/orchestrators,
generates the same production-ready YAML + Python scaffold as the CLI
generator. (2) **The CLI generator** — `./k9_generator.sh preview <AppName>`
from the `k9-aif-framework` repo root, for typing the structure directly
rather than designing it visually. Studio is the recommended starting
point for someone new to the framework; the generator suits someone
already comfortable with the ABB/SBB structure who wants to move fast in
a terminal.

## Do I need to write code to use K9-AIF?

Not to get a working scaffold — K9X Studio generates real, runnable
Python + YAML from a visual design, no code required to produce the
starting point. You do write code once you're customizing agent logic
beyond the generated stub (the actual LLM prompts, business rules,
integrations) — the generated scaffold gives you a correctly-structured
`BaseAgent` subclass to fill in, not a finished solution.

## What's the difference between an ABB and an SBB, and which do I write?

See the glossary for the precise definitions. Practically: you almost
never touch an ABB (`k9_core/`) — those are the framework's own abstract
contracts. You write SBBs — concrete agents/squads/orchestrators in
`examples/<YourApp>/` or `k9_projects/<YourApp>/` that extend the ABB
contracts. If you find yourself editing a file under `k9_core/` to make
your app work, that's a sign you should be extending a `Base<Concern>`
class instead, not modifying the base itself.

## How do I run an example app locally, like this one (k9chat)?

From the `k9-aif-framework` repo root: `./run_k9chat.sh` (or the
equivalent `run_<app>.sh` script for other examples — check the repo
root for the full list). Requires a `.env` file (copy `.env.example` in
that example's own folder) pointing `OLLAMA_BASE_URL` at a reachable
Ollama server with your chosen models pulled.

## Where can I learn more beyond this chat?

`blog.k9x.ai` has the deepest, most narrative coverage — real incidents,
architecture reasoning, and pattern write-ups, not just reference docs.
`k9-aif-framework`'s own `CLAUDE.md` and `SKILLS.md` (repo root) are the
authoritative technical reference for the execution hierarchy, governance,
and step-by-step recipes for common tasks (adding a provider, choosing an
agent pattern, wiring Kafka). `k9x.ai` is the umbrella site linking the
whole ecosystem (Studio, HIL, Continuum, Satan, the Enterprise Repository).

## What is K9X Satan, and do I need it?

`k9x_satan` (`satan.k9x.ai`) is the adversarial red-team harness — it
attacks a K9-AIF solution's governance/security layers (k9x_Shield, Zero
Trust) to prove they actually contain real attacks, not just claim to.
You don't need it to build a solution; it exists to validate one you've
already built, and is the reference implementation for what real
defense-in-depth wiring looks like if you're adding governance to your
own SBB.

## Is K9-AIF tied to one LLM provider?

No — model access goes through `ModelRouterFactory`/`K9ModelRouter` and
`LLMFactory`, both config-driven. Ollama (local/self-hosted) is the most
common default in examples and this chat's own backend, but the same
`InferenceRequest` contract works against any configured provider adapter
without changing agent code — switching providers is a config change, not
a code change.
