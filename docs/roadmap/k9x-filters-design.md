# K9X Filters: design

Status: version 1 built in k9-aif 1.32.0 (opt-in, off by default). Later versions listed at the end.

## The idea in one line

**Governance asks "is this allowed?". Filters ask "is this in the right shape?"**

Shield, Guardian and Zero Trust decide: allow, block, send to a person. They never change a payload
that passes. A filter changes what flows: it removes, labels, normalises, attaches. It never blocks
for policy; a filter that wants to block is a Shield check.

## Why

Every application built on an agent framework shapes its model input and output by hand, inside its
agents, each one differently, and nothing records it:

- **Blind truncation.** `context = source[:8000]` keeps whatever came first. If the relevant section
  sits after character 8000, the model never sees it, and nothing says so.
- **Hand-written JSON extraction.** Code fences, prose around the JSON, a trailing comma: each
  application handles a different subset, and the next step crashes on what it missed.
- **Sources attached by hand**, or not at all.
- **Facts the platform already knows are unreliable** (an Origin answer flagged quarantined, in
  review, in conflict) reach the model unless each agent checks the flags itself. Most don't.
- **Hidden characters pass the pattern checks.** Verified on k9-aif 1.31.1: Shield's
  `PromptInjectionCheck` blocks "ignore all previous instructions" but passes the same text written
  with a zero-width space inside a word, in fullwidth letters, or in invisible Unicode tag
  characters. The model can still read all three.

Filters make that shaping part of the framework: configured once, run for every agent by
construction (like governance), tested once, recorded every time.

| Benefit | Before | With filters |
|---|---|---|
| The model sees the relevant part | First N characters, whatever they are | Highest-scoring chunks within a budget; policy and task always kept |
| Nothing disappears silently | Cut-off text leaves no trace | Every removal recorded (`FilterApplied`); a required part that doesn't fit fails the agent |
| Less agent code | Each agent truncates, parses, attaches | Declared in agent YAML; the agent keeps its own logic |
| Same behaviour everywhere | Many extractors, many edge cases | One tested filter; a fix lands with a framework upgrade |
| Unreliable facts kept out | Each agent checks Origin flags, or doesn't | Quarantined facts removed; in-review/conflict facts labelled |
| Harder to inject | Hidden characters pass Shield | Normalised before Shield screens |
| Answers carry evidence | Built per application | `sources` attached from Origin's provenance |
| Auditable | What the model said | Also what it was given, and what was withheld |

"Better answers" and "fewer tokens" are goals, to be measured (shaped vs unshaped, per model) before
they are claimed.

## Where filters run

Two points in version 1, both in the `BaseAgent` wrapper (`__init_subclass__`), so every agent class
gets them without code:

```
caller → [filters IN] → Shield/Guardian pre → agent.execute() → [filters OUT] → Shield/Guardian post → caller
```

- **In** runs on the payload the agent receives, **before the agent's own code has run**. The payload
  is still a dict of named parts (the query, an Origin answer, retrieved chunks, an email), which is
  what makes pruning and labelling possible.
- **Out** runs on `result["output"]` (a dict result with an `output` key) and may add fields to the
  result (`sources`, `artifacts`).
- **Governance screens the final form at every boundary.** In: Shield screens exactly what the agent
  will receive. Out: anything a filter adds to the output is screened.
- The loop agents (`BaseValidationLoopAgent`, `BaseCriticActorAgent`) run their own pre/post and call
  the same filter points around their loop.
- `execute_stream()`: in-filters run before the first chunk; out-filters do not run on a streamed
  reply (the chunks have already been sent). The agent logs this once.

Not covered in version 1: the orchestrator adapters' own model calls (OpenAI Agents SDK, Claude
Agent SDK, CrewAI, LangGraph). `K9OpenAIAgent` is a `BaseAgent`, so it is covered.

### Why not inside llm_invoke() (yet)

At the model call the agent has already built its prompt: `InferenceRequest.prompt` is one string,
and nothing can tell the policy from the retrieved text from the untrusted email, so nothing can be
reordered. And `llm_invoke()` has no point between choosing the model and calling it; both happen in
`router.invoke()`. The model-call point is a later version (below), together with labelled prompt
parts on `InferenceRequest`.

## The contract

```
k9_aif_abb/
├── k9_core/filters/base_filter.py   BaseFilter, FilterResult, FilterContext, FilterChain, FilterError
├── k9_filters/                      the OOB filters
└── k9_factories/filter_factory.py   FilterFactory (OOB names; register(); class: + module:)
```

```python
class BaseFilter(ABC):
    name: str                         # how config refers to it
    filter_type: str                  # what it does: "normalize", "attention", "json_output", ...
    applies_to = ("in", "out")        # directions it runs in

    def filter_in(self, payload, ctx: FilterContext) -> FilterResult    # default: unchanged
    def filter_out(self, output, ctx: FilterContext) -> FilterResult    # default: unchanged

FilterResult(value, record={}, result_fields={})   # result_fields: out only, merged into the result
FilterContext(agent, layer, config, direction, state)  # state: shared by all filters for one call
```

A filter must not:
- raise `PermissionError` (blocking is governance's job: the chain turns it into `FilterError`);
- publish to Kafka or hold a message bus;
- swallow its own errors: a filter that raises stops the agent, like any agent failure.

Every filter's `record` is logged and emitted as a `FilterApplied` trace event.

## Configuration

Application config (`config/config.yaml`):

```yaml
filters:
  enabled: true                 # off unless true
  chain:                        # run order
    - text_normalize
    - attention
    - json_output
    - provenance
    - {name: ticket_ids, class: TicketIdFilter, module: my_app.filters.ticket_ids}   # SBB filter
```

Agent YAML (merged into the agent's config at the top level by `AgentLoader`):

```yaml
agent_filters: [text_normalize, attention]   # optional: narrow the chain for this agent; [] = none
attention:            {...}                  # each filter reads its own section
json_output:    {...}
```

An unknown name in `agent_filters`, or a filter that can't be imported, raises when the agent is
built: never a silent skip.

## OOB filters (version 1)

### `text_normalize` (K9TextNormalizeFilter), in

For every string in the payload: Unicode NFKC (fullwidth and other compatibility forms become their
plain letters), invisible format characters removed (zero-width space/joiner/non-joiner, word joiner,
byte-order mark, bidirectional overrides and isolates), and Unicode tag characters (U+E0000 to
U+E007F, invisible text the model can read) **revealed** as their ASCII letters so Shield screens
them (`tag_chars: reveal`, the default; `strip` removes them). Runs first. Records how many
characters were changed, per field.

### `attention` (K9AttentionFilter), in

Works only from the parts the agent declares; an agent with no `attention:` section passes through.

```yaml
attention:
  pinned:     [policy, task]       # never pruned
  retrieved:  [policy_chunks]      # list of chunks: scored, de-duplicated, pruned to the budget
  untrusted:  [vendor_email]       # labelled untrusted; kept, never pinned
  query_key:  query                # what relevance is scored against
  budget_tokens: 6000              # pinned + retrieved (estimate: 4 characters per token)
  order: score                     # kept chunks by score (default) or original order
```

1. **Quarantine.** A declared part that is a k9x Origin answer flagged `quarantined` is removed.
   A pinned part that is quarantined fails the agent (it can't run on a required fact it may not use).
   Parts flagged `in_review`, `conflict` or `verification_failed` are labelled `unverified`.
2. **Score** each retrieved chunk against the query (lexical overlap in version 1).
3. **De-duplicate** near-identical chunks.
4. **Prune to the budget**, highest score first. Pinned parts are never pruned; if they alone exceed
   the budget, the agent fails (`FilterError`) instead of running on a cut-down policy.
5. **Label.** Adds `_attention` to the payload: for each declared part its role, trust, source and
   what was kept. Values are never rewritten, so the agent's parsing still works.
   `wrap_untrusted(text, source)` gives the agent a standard delimiter for untrusted text.
6. **Record** what was removed and why, and the token estimate before and after.

### `json_output` (K9JsonOutputFilter), out

Named `json_output`, not `structured_output`: `K9OpenAIAgent`'s agent YAML already uses `structured_output:` for
the OpenAI Agents SDK's typed output, and the two must not read each other's settings.

For an agent that declares `json_output:` (`required: [keys]`, optional `type: object|array`,
optional full JSON Schema under `schema:`, which needs the `jsonschema` package): finds the JSON in
the model's text (plain JSON, a fenced block, or the first complete object/array inside prose),
validates it, and returns the parsed value as the output. No valid JSON, or a missing required key,
fails the agent with the reason. No fallback to the raw text.

### `provenance` (K9ProvenanceFilter), in + out

In: notes every k9x Origin answer in the payload. Out: adds `sources` to the result: entity, id,
`source`, `as_of`, `version` and any flag that is set, for each one. The output itself is unchanged.

### Planned: `deliver` (K9DeliverFilter), out

Calls a formatter agent (Markdown, PDF, JSON) on the output, stores the file in object storage and
adds `artifacts: [{uri, media_type, title}]` (the HIL artifact shape) to the result. Configured only
on the step that produces the deliverable, never in the application-wide chain. Waits for the
formatter agents (`BaseFormatterAgent`, `WebFormatterAgent`) to become real: they are stubs today.

### Not filters

- PII masking stays in Zero Trust (`SensitiveDataLossGuard`): one masker, not two.
- Blocking stays in Shield.
- Summarising a squad's earlier results stays in squad `synthesis:` (`K9ContextSynthesizerAgent`).
- Rendering a deliverable is a formatter agent's job; a filter may call one (`deliver`).

## Writing a filter (SBB)

```python
# my_app/filters/ticket_ids.py
import re
from k9_aif_abb.k9_core.filters.base_filter import BaseFilter, FilterResult

class TicketIdFilter(BaseFilter):
    name = "ticket_ids"
    filter_type = "normalize"
    applies_to = ("out",)

    def filter_out(self, output, ctx):
        if not isinstance(output, str):
            return FilterResult(output)
        new, n = re.subn(r"TCK-\d+", "[ticket]", output)
        return FilterResult(new, record={"replaced": n})
```

Add it to `filters.chain` with `class:` and `module:`, or `FilterFactory.register("ticket_ids",
TicketIdFilter)` at start-up. Recipe and test template: SKILLS.md, "Write a custom filter".

## Later versions

- **Model-call point** in `llm_invoke()`: route, then shape for the chosen model, then call (a router
  method that calls the model for a decision already made), with labelled prompt parts on
  `InferenceRequest`. That is where ordering (policy first, task last), delimiters and layout per
  model belong. Filters there may only reorder and wrap, never write new text, because `llm_invoke()`
  screens the request before routing.
- **Embedding scorer** for `attention` (`EmbeddingServiceFactory`).
- **Compression** with a small model: must run at the agent's input, before Shield, because it writes
  new text.
- **`deliver`**, after the formatter agents are real.
- **Adapters:** the OpenAI adapter's `K9ModelProvider` can take the model-call point.
- **Evidence:** shaped vs unshaped runs per model (K9X Arena), and a poisoned-document attack with and
  without the filters (K9X SATAN).
