# k9x Origin — design (K9-AIF 1.18, draft for review)

**Status:** built in K9-AIF 1.18.0 (2026-10-13). **Author:** Ravi Natarajan. **Date:** 2026-10-13.
**Reference implementation:** K9X Streams (streams.k9x.ai), as K9X Satan is for k9x Shield.

---

## 1. What k9x Origin is

k9x Origin answers one question for an agent: **what is true right now about this entity, and where did that come from?**

It is built into the framework, like k9x Shield. A solution switches it on in `config.yaml`, describes its entities and sources in `config/origin.yaml`, and its agents make one call. There is no separate service, repository or site.

**Origin states facts; it makes no business decisions.** It returns the current value with `as_of`, `source`, `version` and flags. Whether a claim over $5,000 needs a person, or whether an hour-old value is good enough, is a business rule, evaluated by a rules step in the squad (section 3.6).

### Principles

1. **One call for the agent.** `get_current(entity, id)`. Nothing else to learn, no client per source.
2. **All wiring in configuration.** Which entities exist, where each one's data comes from, which steps verify against the system of record: all in `origin.yaml`, never in agent code. The same agent works whether Origin answers from streams, from the system of record, or both.
3. **Fetching is hidden; provenance is not.** Every answer says where it came from (`source`) and when (`as_of`).
4. **Governed in, governed out.** k9x Shield screens every event on the way in, every request, and every answer on the way out.
5. **A read model, never a system of record.** Agents read through Origin; they act through the systems that own the data.
6. **Conflicts are flagged, never hidden.** A status that reverses, a late contradicting event, a disagreement with the system of record: the answer says so. Whether that goes to a person is a business rule (by default, it does).
7. **Don't reinvent data access.** Organizations already run data lakes, warehouses, streaming platforms and their MCP servers. Origin points at them through the framework's existing adapters and MCP client.

---

## 2. Where it sits

```
 Sources (ERP, payments, screening, CDC, logs, IoT)
   │  events                                   │  on demand (read-through / verify)
   ▼                                           │
 [optional] Flink / Kafka Streams curation     │
   ▼                                           │
 K9-AIF context fabric (k9_streams)            │
   KafkaEventFabric → mapper → Shield gate     │
   → projections                               │
   ▼                                           ▼
 ┌──────────────────────── k9x Origin (k9_origin) ─────────────────────────┐
 │  Live state (memory / Redis, LRU)   Sources (system of record adapters) │
 │  Resolver: scope → request Shield → state → freshness → read-through    │
 │            → verify → flags → answer Shield → provenance                │
 │  Conflict detector → domain event (via Router) → review → K9X HIL       │
 └──────────┬───────────────────────────────────────────────┬──────────────┘
            │ live_context (injected)                        │ MCP tools
            ▼                                                ▼
     Orchestrator ──► Squad ──► Agent ─────── get_current ───┘
```

- **k9_streams** (1.17) stays the ingest side: fabric, mappers, gate, projections.
- **k9_origin** (1.18) is the answering side: resolver, sources, policy, conflicts, the MCP surface.
- `ContextMCPServer` (1.17) becomes `OriginMCPServer`, Origin's MCP surface; `BaseOrchestrator.context_state` becomes `origin`.

**Names in code** (the framework's `Base<Concern>` / `K9<Concern>` pattern):

| What | Name |
|---|---|
| Package | `k9_aif_abb/k9_origin/` |
| ABB / built-in | `BaseOrigin` / `K9Origin` |
| Factory | `OriginFactory` |
| Answer | `OriginAnswer` |
| MCP surface | `OriginMCPServer` (`ContextMCPServer` kept as an alias) |
| Config | key `origin:` in `config/config.yaml`; file `config/origin.yaml` |
| Agent tools | `get_current`, `recent_changes`, `query` |

---

## 3. Interfaces

### 3.1 For agents: three operations (MCP tools, also callable in-process)

| Operation | Returns | Typical use |
|---|---|---|
| `get_current(entity, id)` | One `OriginAnswer` | "Is this invoice still approved and unpaid?" |
| `recent_changes(entity, id, window_seconds=600)` | The ordered changes with time and source | "What happened to this claim in the last ten minutes?" |
| `query(entity, filters)` | Matching entities, each an `OriginAnswer` | "Approved invoices over $10,000" |

Agents never pass a mode, a source or a freshness limit. Policy decides.

### 3.2 The answer (`OriginAnswer`)

```json
{
  "entity": "invoice", "id": "INV-1037", "found": true,
  "value": { "status": "approved", "amount": 47157.98, "vendor_id": "V-03" },
  "as_of": "2026-10-13T14:02:07Z", "age_seconds": 2.1,
  "version": "erp:lsn:0/1A2B3C",
  "source": { "kind": "stream", "topic": "ap.invoice.updated", "offset": 189 },
  "flags": { "quarantined": null, "in_review": false, "conflict": null },
  "verified": null,
  "history_available": true
}
```

| Field | Meaning |
|---|---|
| `as_of`, `age_seconds` | When the value last changed at its source, and how long ago: facts for business rules, not a verdict |
| `source.kind` | `stream` (live state), `system_of_record` (read-through), or `both` (verified) |
| `version` | The source's own ordering key (database log position, event version). Used for conditional actions |
| `flags.quarantined` | An event for this entity was refused by Shield; which check, when |
| `flags.in_review` | A K9X HIL case is open for this entity; no agent acts until it is decided |
| `flags.conflict` | What conflicted (reversal, late event, disagreement) |
| `verified` | On steps that require it: `{against, agrees, differences[]}`, only for fields that system owns |
| `history_available` | `false` after eviction and re-fetch: history is unknown, not empty |

Refusals keep the same shape: `{"refused_by_governance": true, "reason": ...}`.

### 3.3 For orchestrators: automatic

A squad declares in `origin.yaml` what it needs. Before the squad runs, the Orchestrator resolves it and places the answers in `payload["live_context"]`. No orchestrator code.

### 3.4 Extension points (ABBs a solution implements)

| ABB | A solution writes | Built in |
|---|---|---|
| `BaseContextProjection` | One per business event (unchanged from 1.17) | — |
| `BaseEnvelopeMapper` | Only for an unusual source format | native, debezium, log_line, auto |
| Sources | Nothing new: Origin reuses the framework's adapters | `mcp`: the framework's MCP client (any MCP server, including data platforms' own); `api`: `BaseApiAdapter`; `sql`: `BaseDataAdapter` |
| `BaseContextState` | Rarely | `InMemoryContextState`, `RedisContextState` |
| `BaseConflictRule` | Only for a conflict the built-ins miss | reversal, late_event, disagreement (flags only) |

### 3.5 Relationship to the retriever, the enricher and MCP

| | Retriever (`BaseRetriever`, `K9Retriever`) | k9x Origin |
|---|---|---|
| Question | "What do our documents say about this?" | "What is true about INV-1037 right now?" |
| Input | Free text + intent | Entity + key |
| Answer | Ranked passages with a similarity score | One exact record with `as_of`, `version`, `source` |
| Data | Knowledge (policies, contracts, manuals), slow-changing | State (invoices, claims, vendors), fast-changing |
| Engine | Vector database, embeddings | Live state from streams + system of record |

No overlap: a squad often uses both (the contract clause from the retriever, the payment status from Origin). Origin does not implement `BaseRetriever`; the contracts answer different questions.

**Enricher.** `live_context` injection adds facts to the payload deterministically, with provenance. `EnrichmentAgent` interprets or transforms content; it consumes `live_context` like any agent.

**MCP.** Origin *is* an MCP server (its three tools; 1.17's `ContextMCPServer` becomes its MCP surface), reached with the framework's existing MCP client. It does not replace a solution's other MCP servers.

**How many calls does an agent make?**

- *Reading:* zero or one. The Orchestrator usually injects `live_context` before the agent runs; the agent calls `get_current` once only to re-check before acting. Read-through, verify and conflict checks happen inside that one call.
- *Acting:* one more, deliberately separate: the action goes to the system that owns it (e.g. `release_payment` on the treasury MCP server or API), carrying Origin's `version` so it is refused if anything changed. Origin is read-only.
- *One endpoint, optionally:* `register_on(mcp)` places Origin's tools on the solution's existing MCP server, next to its action tools.

### 3.6 Business rules: decisions stay outside Origin

Origin supplies facts; a rules step decides. In a squad, a rules agent (`BaseRulesAgent`, calling a `BaseRulesAdapter`: Drools, a decision service, OpenL, Easy Rules) evaluates the payload including `live_context`, and raises `RequiresHIL` when a rule says so:

```yaml
# rules, not origin.yaml (illustrative)
- when: claim.amount > 5000                     then: hil
- when: live_context.claim.flags.conflict       then: hil      # default rule
- when: live_context.invoice.age_seconds > 3600 then: hold     # only if the business cares
```

**Built in 1.18:** `BaseRulesAdapter` and `BaseRulesAgent` had no built-in implementation before this release. 1.18 adds `K9RulesAdapter` (rules in YAML, for teams without a rules engine), `RestRulesAdapter` (a decision service: Drools/KIE, ODM, OpenL, Corticon) and `K9RulesAgent` (a `hil` decision raises `RequiresHIL`; an engine that cannot answer escalates).

### 3.7 For operations

`GET /origin/health` (lag per topic, memory, evictions), `GET /origin/conflicts` (open conflicts and their HIL cases), drift report (stream vs system of record), all read-only. Releasing `in_review` happens only through the K9X HIL decision.

---

## 4. Under the hood

### 4.1 Ingest (continuous)

1. Event arrives on the fabric; the topic's **mapper** makes an `EventEnvelope`.
2. **Shield gate**: refused → mark `quarantined` (pinned, never evicted), content never applied.
3. **Projections** derive the updates (one event may update several entities: a payment updates the invoice and creates the payment).
4. **Apply by source order**, not arrival: compare the event's `version` / source time with the entity's; an older event goes to history only. *(1.17 applies in arrival order; this is the first thing 1.18 fixes.)*
5. **Conflict rules** run on the change (e.g. `status` approved → disapproved within the window). On conflict the entity is flagged, and a `origin.conflict` domain event is emitted for the Router; business rules decide what follows (by default, a K9X HIL case, during which the entity is `in_review`).
6. **Store**: update in place (latest replaces old for that entity), append to the entity's history; when memory is full, evict the least recently *used* entity.

### 4.2 Answer (per call)

```
get_current(entity, id)
 1. scope          entity allowed for this agent?            no → refused
 2. request Shield injection / PII solicitation in args?     yes → refused
 3. state lookup   in live state?
 4. found?         in live state                              → step 6
 5. read-through   missing and a source is set?              → fetch from system of record,
                                                               store, source.kind = system_of_record
 6. verify         this squad step requires verification?    → also fetch, compare owned fields,
                                                               disagreement → conflict flag (4.3)
 7. flags          quarantined / in_review / conflict attached, never hidden
 8. answer Shield  PII values, planted instructions          withheld if refused
 9. audit          trace event: who asked, what, source, age, outcome
```

### 4.3 Conflict → person

`origin.conflict` event → Router → review orchestrator → rules → `RequiresHIL` → K9X HIL case showing both values, their sources, times and order → reviewer decides → the decision resumes the flow and clears `in_review`. Origin never publishes to Kafka itself; the Router and Orchestrator own messaging, as everywhere in K9-AIF.

### 4.4 Rules that are not configurable

- Quarantine and `in_review` are always returned. No setting hides them.
- Read-through never overrides a quarantine: a refused event is not "cleaned" by fetching from the database.
- An older event never overwrites newer state.
- Production refuses an ungoverned Origin (no Shield), as it refuses ungoverned agents.

---

## 5. Configuration

### 5.1 `config.yaml` (switch it on)

```yaml
origin:
  enabled: true
  config: config/origin.yaml
  state: { provider: redis, max_memory: 10gb }   # memory | redis
streams:
  enabled: true                                   # off: Origin answers from the systems of record only
  provider: kafka
security:
  shield: { enabled: true, ... }                  # Origin reuses the solution's Shield
```

`.env` holds only addresses and credentials (`KAFKA_*`, `REDIS_URL`, `ERP_API_TOKEN`, `AP_DB_URL`).

### 5.2 `config/origin.yaml` (the solution's entities and sources)

```yaml
# k9x Origin — Accounts Payable
entities:
  invoice:
    key: invoice_id
    system_of_record: erp_api              # read-through and verify go here
    owned_fields: [status, amount, vendor_id, due]   # what erp_api is authoritative for
    conflicts:
      watch: [status]                      # flagged; business rules decide what follows
      reversal_window_seconds: 300
  vendor:
    key: vendor_id
    system_of_record: vendor_db
    owned_fields: [name, bank_account_ref, status]
  payment:
    key: payment_id
    system_of_record: treasury_api

sources:   # point at what the organization already runs; nothing new to build
  erp_api:      { type: mcp, server: "${ERP_MCP_URL}", tool: get_invoice }          # MCP client
  vendor_db:    { type: sql, adapter: vendor_master }                               # BaseDataAdapter
  treasury_api: { type: api, adapter: treasury }                                    # BaseApiAdapter

topics:
  ap.invoice.updated: { mapper: auto }
  dbserver.public.vendors: { mapper: debezium }
  ap.payment.posted: { mapper: auto }

squads:
  payment_release:
    live_context: ["invoice:{invoice_id}", "vendor:{vendor_id}"]   # filled from the payload
    verify_before: [release_payment]       # irreversible step: stream + system of record

agents:
  PaymentReleaseAgent:
    allowed_entities: [invoice, vendor, payment]
  CashForecastAgent:
    allowed_entities: [invoice]

governance:
  request_checks: [PromptInjectionCheck, PIIRequestCheck]
  answer_checks:  [PromptInjectionCheck, PIIBoundaryCheck]
```

Business rules (HIL thresholds, what to do with old values or conflicts) live with the rules step, not here.

Every setting has a safe default; a minimal file is `entities:` with a `key` each.

### 5.3 Where Origin answers from, with the same agent code

| `streams.enabled` | `system_of_record` set | Origin answers from |
|---|---|---|
| true | no | Live state only |
| true | yes | Live state, read-through on miss or age, verify where declared |
| false | yes | System of record only (a governed, audited API facade) |
| false | no | Origin refuses to start: nothing to answer from |

---

## 6. What a solutions architect does

1. **List the decisions.** Which agent actions are irreversible (pay, approve, ship, update)? These drive everything else.
2. **List the entities those decisions read**, and for each, its **system of record** and the fields it owns.
3. **Find each entity's events.** Topic, format (native, CDC, logs), and whether curation (Flink) is needed first.
4. **Write one projection per business event** (the only domain code).
5. **Point at the existing sources** for read-through and verify: the data platform's MCP server, an API or a database, through the framework's adapters, with credentials in `.env`.
6. **Mark the irreversible steps** with `verify_before`.
7. **Define conflicts** (`watch`, windows): what counts as a reversal for this entity.
8. **Write the business rules** for the rules step: HIL thresholds, what to do on a conflict, whether an old value matters for this decision.
9. **Scope each agent** (`allowed_entities`): least privilege.
10. **Make the actions conditional** in the system of record: send the `version` with the action so it is refused if anything changed. Origin narrows the window; this closes it.
11. **Size it** (memory / Redis, Flink or not) and **test it**: the K9X Streams scenarios and threat simulator are the template (duplicate, reversal, poisoned event, PII request, out-of-scope).

---

## 7. Compatibility

- Solutions without `origin:` in `config.yaml` change nothing.
- 1.17 APIs keep working: `ContextMCPServer`, `BaseOrchestrator(context_state=...)`, `StreamsFactory.create_state()`; they become thin paths into Origin.
- K9X Streams moves to `origin.yaml` as the reference.

## 8. Build order

1. Apply by source order + `version` in answers (correctness first).
2. `k9_origin` package: `BaseOrigin` / `K9Origin`, `OriginAnswer`, `OriginFactory`, `origin.yaml` loader, scope and Shield steps (from 1.17).
3. Sources through the existing adapters (MCP client, `BaseApiAdapter`, `BaseDataAdapter`); read-through; verify.
4. Conflict flags → domain event → rules step → HIL round trip; built-in YAML rules adapter and `RequiresHIL` from a rule decision.
5. `RedisContextState` with LRU, pinned quarantine, `history_available`.
6. Orchestrator auto-injection from `squads:`; per-agent scope; `register_on(mcp)` for existing MCP servers.
7. Docs (Developer Guide, diagrams), K9X Streams migrated, catalog entries, tests at each step.

## 9. Decisions on the open questions (Ravi, 2026-10-13)

1. **Freshness:** Origin returns whatever is current, with `as_of` and `source` as facts. No staleness policy in Origin; business rules decide if age matters.
2. **Business rules:** decisions (e.g. claim over $5,000 → HIL, conflict → HIL) belong to a rules step (`BaseRulesAgent` / `BaseRulesAdapter`), not to Origin. Built-in rules adapter added as a 1.18 companion.
3. **Config location:** `config/origin.yaml`, next to `config/config.yaml`.
4. **Data sources:** no new connectors. Point at what organizations already run (data platforms, warehouses, streaming platforms, their MCP servers) through the framework's existing adapters and MCP client.
5. **Names in code:** `k9_origin`, `BaseOrigin` / `K9Origin`, `OriginFactory`, `OriginAnswer`, `OriginMCPServer` (section 2).

Still open: per-agent scope from Zero Trust identity later; Flink as a documented pattern in 1.18 (proposed) rather than a state backend.
