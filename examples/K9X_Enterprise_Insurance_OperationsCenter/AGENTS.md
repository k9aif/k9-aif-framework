# AGENTS.md — K9X Enterprise Insurance Operations Center

Reference guide for all agents, squads, and model assignments in the EOC.
Read alongside `SKILLS.md` (how to add agents) and `CLAUDE.md` (framework architecture).

---

## Agent Reference

| Agent | Pattern | Model | LLM Call | Emits | Governance |
|---|---|---|---|---|---|
| ClaimsTriageAgent | reasoning | `reasoning` | Only when completeness_score == 1.0 | `ClaimsTriageCompleted` | pre only |
| AdjudicationAgent | reasoning | `reasoning` | Always | `AdjudicationCompleted` | pre + post |
| GuardAgent | guard | `guardian` | Always — no fallback | `GuardCheckCompleted` | none (IS governance) |
| FraudDetectionAgent | reasoning | `reasoning` | Always | `FraudAssessmentCompleted` | none |
| DocumentExtractorAgent | extraction | `extraction` | When text available | `DocumentExtractionCompleted` | none |
| EscalationAgent | gate | none | Never — deterministic | `EscalationRaised` | none |
| GraphSyncAgent | integration | none | Never — Neo4j only | `GraphSyncCompleted` | none |
| AuditAgent | audit | none | Never — DB write only | `AuditEntryWritten` | none |

---

## Agent Details

### ClaimsTriageAgent
Validates claim completeness, matches coverage, assigns priority (critical / high / normal / low) based on amount. Calls LLM only when the claim is 100% complete — no reasoning on incomplete data.

- **Input:** `claim_id`, `claimant_id`, `policy_id`, `claim_type`, `amount_claimed`
- **Key logic:** completeness_score, amount thresholds ($100k critical / $25k high / $5k normal), anomaly detection > $10M
- **Output:** completeness_score, priority, coverage_match, triage_reasoning, confidence
- **Routing:** → AdjudicationAgent on success, → EscalationAgent on failure

---

### AdjudicationAgent
Policy coverage reasoning and liability determination. Produces a structured decision with rationale. Confidence < 0.75 triggers automatic escalation via EscalationAgent.

- **Input:** triage result + original claim payload
- **Decisions:** `approve | deny | partial | escalate`
- **Output:** decision, confidence, rationale, recommendation, prompt_hash, response_hash
- **Routing:** → GuardAgent on success, → EscalationAgent on failure

---

### GuardAgent
Pre/post-inference governance gate. Applies regex PII detection (SSN, credit card, email, phone), tokenizes PII using deterministic SHA-256 (same value → same token, never stored), then invokes Granite Guardian for AI-powered policy compliance. **Hard requirement — no fallback model.**

- **PII handling:** tokenization/pseudonymization → vault isolation → redacted text to LLM
- **Output:** passed (bool), pii_detected, pii_findings, policy_violations, guardian_output
- **Governance note:** GuardAgent is the governance implementation — it does not go through the governance pipeline itself

---

### FraudDetectionAgent
Two-stage fraud detection: rule-based keyword/amount signals first, then LLM deep reasoning. Final risk score = max(rule_score, llm_score). Auto-escalates at risk_score ≥ 0.8.

- **Signals:** keyword matching, amount thresholds, repeat claimant flag
- **Recommendations:** `monitor | flag | block | escalate`
- **Output:** risk_score (0.0–1.0), signals, rule_signals, recommendation, rationale, confidence
- **Auto-escalation threshold:** 0.8

---

### DocumentExtractorAgent
OCR and structured extraction pipeline. Accepts raw text, file path (Tesseract OCR), or a document payload routed to the Docling MCP server. Uses extraction-capable model (Granite) to produce validated JSON. Low hallucination tolerance required.

- **Phase 1 OCR:** Tesseract subprocess (when `file_path` provided and Tesseract is installed)
- **Phase 2 OCR (MCP):** `MCPHttpConnector` (ABB) → POST to Docling at `http://192.168.1.98:5001/v1/parse` → returns clean Markdown (PDFs, DOCX, images, tables)
- **MCP ABB:** `k9_core/integration/mcp_http_connector.py` — swap connector type in config without touching squad or orchestrator code
- **Extracts:** document_type, claimant_name, policy_number, claim_number, incident_date, amount, provider, description, signatures_present
- **Output:** extracted_fields (JSON), validation_status, ocr_applied, document_id

---

### EscalationAgent
Purely deterministic — no LLM. Confidence gate that packages a structured EscalationTicket when confidence < threshold (default 0.75), guard_passed = False, or force_escalate = True. Powers the HITL queue in the Web UI.

- **Triggers:** confidence < threshold OR guard_passed == False OR force_escalate == True
- **Priority assignment:** confidence < 0.3 or guard failed → critical; < 0.5 → high; < threshold → normal
- **Output:** should_escalate, ticket_id, EscalationTicket with full context package

---

### GraphSyncAgent
Neo4j MERGE operations for entity graph. Creates/updates Claimant, Policy, Claim, Document nodes and typed relationships. Fully idempotent (MERGE not CREATE). Degrades gracefully when Neo4j is unavailable — returns `status: skipped`, never raises.

- **Tools:** Neo4j driver (bolt://192.168.1.98:7687)
- **Nodes:** Claimant, Claim, Policy, Document
- **Relationships:** Claimant→[FILED]→Claim, Claim→[COVERED_BY]→Policy, Claim→[HAS_DOCUMENT]→Document
- **Config gate:** `eoc.graph_sync_enabled` — set to false to disable without code change

---

### AuditAgent
Immutable audit record writer. Persists AuditEntry to PostgreSQL (prod) or SQLite (dev). Computes SHA-256 hashes for prompt and response — never stores raw LLM text. INSERT OR IGNORE prevents duplicates. Also supports query mode for compliance report assembly. **Never deletes or updates existing records.**

- **Cross-squad:** used by all 7 squads — every pipeline ends with AuditAgent
- **Persistence:** `eoc.audit_entries` table in PostgreSQL
- **Output:** audit_id (AUD-XXXXXXXXXXXX), correlation_id, status (written | error)

---

## Squad Composition

| Squad | Agents (flow order) | Event Trigger |
|---|---|---|
| ClaimsProcessingSquad | ClaimsTriageAgent → AdjudicationAgent → GuardAgent → AuditAgent → EscalationAgent | `ClaimSubmitted` |
| DocumentIntelligenceSquad | DocumentExtractorAgent → GuardAgent → GraphSyncAgent → AuditAgent | `DocumentReceived` |
| RiskAssessmentSquad | FraudDetectionAgent → GuardAgent → AuditAgent → EscalationAgent | `RiskAssessmentRequested` |
| CatastropheResponseSquad | FraudDetectionAgent → AuditAgent | `CatastropheEvent` |
| CustomerServiceSquad | ClaimsTriageAgent → GuardAgent → AuditAgent → EscalationAgent | `CustomerInquiry` |
| PolicyManagementSquad | GuardAgent → AuditAgent | `PolicyEvent` |
| AuditComplianceSquad | AuditAgent | `AuditRequested` |

---

## Model Routing

| Model Alias | Ollama Model | Capabilities | Used By |
|---|---|---|---|
| `general` | llama3.2:1b | general, chat, summarization, customer_intent | Default fallback |
| `reasoning` | granite3-dense:2b | reasoning, adjudication, fraud, audit_report, policy_compliance | ClaimsTriageAgent, AdjudicationAgent, FraudDetectionAgent |
| `guardian` | granite3-guardian:latest | guardrails, policy, confidential, pii_detection | GuardAgent (hard requirement — no fallback) |
| `extraction` | granite3-dense:2b | extraction, structured_output, ocr_post_processing | DocumentExtractorAgent |

---

## Agents That Never Call the LLM

| Agent | Why |
|---|---|
| EscalationAgent | Purely deterministic — threshold comparison and ticket packaging |
| GraphSyncAgent | Integration agent — Neo4j MERGE operations only |
| AuditAgent | Persistence agent — DB writes and SHA-256 hashing only |

---

## Governance Coverage

| Agent | enforce_governance | pre_process | post_process |
|---|---|---|---|
| ClaimsTriageAgent | — | ✅ | — |
| AdjudicationAgent | — | ✅ | ✅ |
| GuardAgent | — | — | — (IS governance) |
| FraudDetectionAgent | — | — | — |
| DocumentExtractorAgent | — | — | — |
| EscalationAgent | — | — | — |
| GraphSyncAgent | — | — | — |
| AuditAgent | — | — | — |

> Governance pre/post processing is applied in the agent's `execute()` by calling `apply_pre_governance()` / `apply_post_governance()`. The governance pipeline is wired in via `require_governance()` at agent init. `K9_ENV=production` causes `enforce_governance()` to raise `PermissionError` if `NoopGovernance` is active.
