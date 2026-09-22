# Best Practices

Scaffold document — sections below are seeded with real, learned entries where
we have them; everything marked `TODO` is a placeholder for later, not yet
written guidance.

## Framework Best Practices

### Model configuration — temperature

Temperature is an SBB-level decision, not a framework-level one — the
framework doesn't prescribe it; whoever authors an SBB's agent YAML sets it
per task, in `inference.llm_factory.models.<alias>.temperature` (see
`SKILLS.md` Skill 1/Skill 2 for where this lives in an agent YAML).

- **Low (0.0–0.3)** — factual responses, coding assistance, data extraction,
  content moderation
- **Medium (0.4–0.7)** — summarization, educational content, problem-solving,
  constrained creative writing
- **High (0.8–1.0)** — brainstorming, open creative writing, marketing
  content, joke generation

### TODO

- ABB/SBB design conventions worth calling out beyond what's already in `CLAUDE.md`
- Governance pipeline patterns (when to extend vs. use OOB)
- Testing conventions for new ABBs/SBBs
- Squad/Orchestrator design patterns worth a named best practice

## Claude Code Best Practices

### Keep CLAUDE.md small and load-bearing

Anthropic's guidance: target 50–150 lines, hard ceiling ~200. Include only
what Claude needs nearly every session — build/test/lint commands, non-obvious
architectural conventions, project-specific rules, common pitfalls Claude
can't infer from the repo itself. A good pruning test: *"would removing this
line regularly cause Claude to make a mistake? If not, remove it."*

We hit this directly on 2026-08-08: `CLAUDE.md` had grown to 395 lines and
was auto-importing `SKILLS.md` (1,582 lines) via `@SKILLS.md`, so every
session force-loaded 1,977 lines regardless of task. Fixed by trimming
`CLAUDE.md` to ~156 lines of load-bearing content, dropping the auto-import,
and preserving the full prior version in `old-CLAUDE.md` rather than deleting
it outright. `SKILLS.md` is now read on demand, not force-loaded.

Path- or language-specific guidance belongs in scoped `.claude/rules/` files,
not the root `CLAUDE.md` — keeps the always-loaded file focused on what
applies everywhere.

### Loose reference files have no special status

A `.md` file sitting in the repo root (or anywhere else) is **not**
auto-loaded by Claude Code just by existing there — only `CLAUDE.md` (and
scoped `.claude/rules/` files) get that treatment. A standalone reference
file only enters context if it's explicitly read, grepped, or pointed to in
a prompt. If content needs to reliably inform Claude's behavior, it belongs
in `CLAUDE.md` (if load-bearing nearly every session), a `.claude/skills/`
skill (if it's something deliberately invoked for a recurring task), or
inline next to the thing it's guiding (e.g. temperature guidance living next
to the actual `temperature:` config key, not in a separate file).

### TODO

- When to use a skill vs. a rule vs. inline CLAUDE.md guidance — decision
  criteria
- Hook design conventions (blocking vs. warning, timeout budgets)
- Memory usage conventions specific to this project
