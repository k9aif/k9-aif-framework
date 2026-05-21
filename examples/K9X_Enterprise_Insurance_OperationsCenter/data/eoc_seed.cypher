// SPDX-License-Identifier: Apache-2.0
// K9-AIF EOC — Neo4j Architecture + Runtime Seed
//
// Seeds the K9-AIF component graph and creates indexes for runtime data.
// Run once against your Neo4j instance before starting the EOC application.
//
// Usage (cypher-shell):
//   cypher-shell -a bolt://192.168.1.98:7687 \
//                -u neo4j -p <password> \
//                --file eoc_seed.cypher
//
// Usage (Neo4j Browser): paste and run in blocks.

// ════════════════════════════════════════════════════════════════════════════
// CONSTRAINTS — enforce uniqueness on all key node types
// ════════════════════════════════════════════════════════════════════════════

CREATE CONSTRAINT k9_component_id IF NOT EXISTS
  FOR (n:K9Component) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT claimant_unique_id IF NOT EXISTS
  FOR (n:Claimant) REQUIRE n.claimant_id IS UNIQUE;

CREATE CONSTRAINT claim_unique_id IF NOT EXISTS
  FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE;

CREATE CONSTRAINT policy_unique_id IF NOT EXISTS
  FOR (n:Policy) REQUIRE n.policy_id IS UNIQUE;

CREATE CONSTRAINT document_unique_id IF NOT EXISTS
  FOR (n:Document) REQUIRE n.document_id IS UNIQUE;

CREATE CONSTRAINT alert_unique_id IF NOT EXISTS
  FOR (n:Alert) REQUIRE n.alert_id IS UNIQUE;

// ════════════════════════════════════════════════════════════════════════════
// INDEXES — fast lookup for runtime graph queries
// ════════════════════════════════════════════════════════════════════════════

CREATE INDEX claim_correlation IF NOT EXISTS
  FOR (n:Claim) ON (n.correlation_id);

CREATE INDEX alert_type IF NOT EXISTS
  FOR (n:Alert) ON (n.alert_type);

// ════════════════════════════════════════════════════════════════════════════
// K9-AIF ARCHITECTURE GRAPH
// Layer 1: EOCRouter (deterministic event router)
// ════════════════════════════════════════════════════════════════════════════

MERGE (router:K9Component:Router {id: 'EOCRouter'})
SET router.label       = 'EOCRouter',
    router.pattern     = 'deterministic',
    router.layer       = 'router',
    router.description = 'Routes incoming events by event_type to squad orchestrators';

// ════════════════════════════════════════════════════════════════════════════
// Layer 2: Squad Orchestrators (one per event domain)
// ════════════════════════════════════════════════════════════════════════════

MERGE (o_claims:K9Component:Orchestrator {id: 'ClaimsProcessingOrchestrator'})
SET o_claims.label       = 'ClaimsProcessingOrchestrator',
    o_claims.event_type  = 'claim_submitted',
    o_claims.topic_in    = 'eoc.claims.in',
    o_claims.topic_out   = 'eoc.claims.out';

MERGE (o_docs:K9Component:Orchestrator {id: 'DocumentIntelligenceOrchestrator'})
SET o_docs.label       = 'DocumentIntelligenceOrchestrator',
    o_docs.event_type  = 'document_received',
    o_docs.topic_in    = 'eoc.documents.in',
    o_docs.topic_out   = 'eoc.documents.out';

MERGE (o_risk:K9Component:Orchestrator {id: 'RiskAssessmentOrchestrator'})
SET o_risk.label       = 'RiskAssessmentOrchestrator',
    o_risk.event_type  = 'fraud_signal_raised',
    o_risk.topic_in    = 'eoc.risk.in',
    o_risk.topic_out   = 'eoc.risk.out';

MERGE (o_policy:K9Component:Orchestrator {id: 'PolicyManagementOrchestrator'})
SET o_policy.label       = 'PolicyManagementOrchestrator',
    o_policy.event_type  = 'policy_change_requested',
    o_policy.topic_in    = 'eoc.policy.in',
    o_policy.topic_out   = 'eoc.policy.out';

MERGE (o_cat:K9Component:Orchestrator {id: 'CatastropheResponseOrchestrator'})
SET o_cat.label       = 'CatastropheResponseOrchestrator',
    o_cat.event_type  = 'catastrophe_alert_issued',
    o_cat.topic_in    = 'eoc.catastrophe.in',
    o_cat.topic_out   = 'eoc.catastrophe.out';

MERGE (o_cust:K9Component:Orchestrator {id: 'CustomerServiceOrchestrator'})
SET o_cust.label       = 'CustomerServiceOrchestrator',
    o_cust.event_type  = 'customer_interaction_logged',
    o_cust.topic_in    = 'eoc.customer.in',
    o_cust.topic_out   = 'eoc.customer.out';

MERGE (o_audit:K9Component:Orchestrator {id: 'AuditComplianceOrchestrator'})
SET o_audit.label       = 'AuditComplianceOrchestrator',
    o_audit.event_type  = 'audit_query_received',
    o_audit.topic_in    = 'eoc.audit.in',
    o_audit.topic_out   = 'eoc.audit.out';

// ════════════════════════════════════════════════════════════════════════════
// Layer 3: Domain Agents
// ════════════════════════════════════════════════════════════════════════════

MERGE (a_triage:K9Component:Agent {id: 'ClaimsTriageAgent'})
SET a_triage.label   = 'ClaimsTriageAgent',
    a_triage.pattern = 'react',
    a_triage.model   = 'reasoning',
    a_triage.layer   = 'agent';

MERGE (a_adj:K9Component:Agent {id: 'AdjudicationAgent'})
SET a_adj.label   = 'AdjudicationAgent',
    a_adj.pattern = 'chain_of_thought',
    a_adj.model   = 'reasoning',
    a_adj.layer   = 'agent';

MERGE (a_doc:K9Component:Agent {id: 'DocumentExtractorAgent'})
SET a_doc.label   = 'DocumentExtractorAgent',
    a_doc.pattern = 'extraction',
    a_doc.model   = 'extraction',
    a_doc.layer   = 'agent';

MERGE (a_fraud:K9Component:Agent {id: 'FraudDetectionAgent'})
SET a_fraud.label   = 'FraudDetectionAgent',
    a_fraud.pattern = 'react',
    a_fraud.model   = 'reasoning',
    a_fraud.layer   = 'agent';

MERGE (a_graph:K9Component:Agent {id: 'GraphSyncAgent'})
SET a_graph.label   = 'GraphSyncAgent',
    a_graph.pattern = 'tool_use',
    a_graph.model   = 'general',
    a_graph.layer   = 'agent';

// ════════════════════════════════════════════════════════════════════════════
// Layer 4: Cross-cutting Governance Agents (appear in every squad)
// ════════════════════════════════════════════════════════════════════════════

MERGE (a_guard:K9Component:GovernanceAgent {id: 'GuardAgent'})
SET a_guard.label   = 'GuardAgent',
    a_guard.pattern = 'guardrails',
    a_guard.model   = 'guardian',
    a_guard.layer   = 'governance',
    a_guard.checks  = ['pii_detection', 'confidence_threshold', 'policy_compliance'];

MERGE (a_audit:K9Component:Agent {id: 'AuditAgent'})
SET a_audit.label   = 'AuditAgent',
    a_audit.pattern = 'audit',
    a_audit.model   = 'general',
    a_audit.layer   = 'audit';

MERGE (a_esc:K9Component:Agent {id: 'EscalationAgent'})
SET a_esc.label       = 'EscalationAgent',
    a_esc.pattern     = 'escalation',
    a_esc.model       = 'general',
    a_esc.layer       = 'agent',
    a_esc.conditional = true;

// ════════════════════════════════════════════════════════════════════════════
// ROUTING RELATIONSHIPS — Router → Orchestrators
// ════════════════════════════════════════════════════════════════════════════

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'claim_submitted',             topic: 'eoc.claims.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'DocumentIntelligenceOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'document_received',           topic: 'eoc.documents.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'RiskAssessmentOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'fraud_signal_raised',         topic: 'eoc.risk.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'PolicyManagementOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'policy_change_requested',     topic: 'eoc.policy.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'CatastropheResponseOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'catastrophe_alert_issued',    topic: 'eoc.catastrophe.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'CustomerServiceOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'customer_interaction_logged', topic: 'eoc.customer.in'}]->(o);

MATCH (r:Router {id: 'EOCRouter'}), (o:Orchestrator {id: 'AuditComplianceOrchestrator'})
MERGE (r)-[:ROUTES_TO {event_type: 'audit_query_received',        topic: 'eoc.audit.in'}]->(o);

// ════════════════════════════════════════════════════════════════════════════
// ORCHESTRATOR → AGENT DISPATCH relationships
// ════════════════════════════════════════════════════════════════════════════

// Claims Processing Squad
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:Agent {id: 'ClaimsTriageAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:Agent {id: 'AdjudicationAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 2}]->(a);
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:Agent {id: 'GraphSyncAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 3}]->(a);
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);
MATCH (o:Orchestrator {id: 'ClaimsProcessingOrchestrator'}), (a:Agent {id: 'EscalationAgent'})
MERGE (o)-[:ESCALATES_TO {conditional: true}]->(a);

// Document Intelligence Squad
MATCH (o:Orchestrator {id: 'DocumentIntelligenceOrchestrator'}), (a:Agent {id: 'DocumentExtractorAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'DocumentIntelligenceOrchestrator'}), (a:Agent {id: 'GraphSyncAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 2}]->(a);
MATCH (o:Orchestrator {id: 'DocumentIntelligenceOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'DocumentIntelligenceOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);

// Risk Assessment Squad
MATCH (o:Orchestrator {id: 'RiskAssessmentOrchestrator'}), (a:Agent {id: 'FraudDetectionAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'RiskAssessmentOrchestrator'}), (a:Agent {id: 'GraphSyncAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 2}]->(a);
MATCH (o:Orchestrator {id: 'RiskAssessmentOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'RiskAssessmentOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);
MATCH (o:Orchestrator {id: 'RiskAssessmentOrchestrator'}), (a:Agent {id: 'EscalationAgent'})
MERGE (o)-[:ESCALATES_TO {conditional: true}]->(a);

// Policy Management Squad
MATCH (o:Orchestrator {id: 'PolicyManagementOrchestrator'}), (a:Agent {id: 'ClaimsTriageAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'PolicyManagementOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'PolicyManagementOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);

// Catastrophe Response Squad
MATCH (o:Orchestrator {id: 'CatastropheResponseOrchestrator'}), (a:Agent {id: 'FraudDetectionAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'CatastropheResponseOrchestrator'}), (a:Agent {id: 'GraphSyncAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 2}]->(a);
MATCH (o:Orchestrator {id: 'CatastropheResponseOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'CatastropheResponseOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);

// Customer Service Squad
MATCH (o:Orchestrator {id: 'CustomerServiceOrchestrator'}), (a:Agent {id: 'ClaimsTriageAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'CustomerServiceOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);
MATCH (o:Orchestrator {id: 'CustomerServiceOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:AUDITED_BY]->(a);

// Audit Compliance Squad
MATCH (o:Orchestrator {id: 'AuditComplianceOrchestrator'}), (a:Agent {id: 'AuditAgent'})
MERGE (o)-[:DISPATCHES_TO {step: 1}]->(a);
MATCH (o:Orchestrator {id: 'AuditComplianceOrchestrator'}), (a:GovernanceAgent {id: 'GuardAgent'})
MERGE (o)-[:GOVERNED_BY]->(a);

// ════════════════════════════════════════════════════════════════════════════
// VERIFICATION — run after seeding to confirm node counts
// ════════════════════════════════════════════════════════════════════════════

// MATCH (n:K9Component) RETURN labels(n) AS type, count(*) AS count ORDER BY count DESC;
// Expected: Router=1, Orchestrator=7, Agent=6, GovernanceAgent=1 → 15 total K9Component nodes
