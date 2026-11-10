# Capability index

Every ABB in `k9_aif_abb`, grouped by concern, with what ships out of the box
(OOB). **Read this before designing anything:** if a concern is listed, build
on its ABB or extend it; never add a parallel mechanism. Business decisions
(rules, limits, policies) are SBB content; the framework supplies the adapters
that evaluate them.

Kept honest by `k9_aif_abb/tests/test_capability_index.py`: it fails when a
`Base*` class in `k9_aif_abb` is missing here, or when this file names a
`Base*` class that no longer exists. Add the row in the same commit as the ABB.
Detail on each concern: `CLAUDE.md` (rules, gotchas) and `SKILLS.md` (recipes).

## Execution: Router → Orchestrator → Squad → Agent

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseComponent` | (infra base: logging, monitor, bus) | `k9_core/base_component.py` |
| `BaseRouter` | `K9EventRouter`, `RouterAgent` | `RouterFactory`; `BaseRouter.admit()` is the auth edge |
| `BaseOrchestrator` | `IntentOrchestrator`, `GovernanceOrchestrator`, `DiagnosticOrchestrator`, the three framework adapters below | `OrchestrationFactory`, `OrchestratorRegistry` |
| `BaseHILOrchestrator` | used by `handle_requires_hil()` | publishes `hil.requests.<queue>`; see CLAUDE.md HIL |
| `BaseSquad` | `IntentSquad`; any squad YAML runs on `BaseSquad` | `SquadLoader.from_agents()` |
| `BaseAgent` | `K9ContextSynthesizerAgent`, `EnrichmentAgent`, `K9RetrievalAgent`, `K9EmbeddingAgent`, `K9DocPreprocessor`, `DoclingParser`, `AsyncAgent`, `ChatAgentABB`, `EncryptionAgent`, `AuthAgent`, `SecretManagerAgent`, `MessageAgent`, `ProcessorAgent` | `AgentLoader` (`class:` + `module:` in agent YAML), `AgentRegistry` |
| `BaseValidationLoopAgent` | `K9ValidationLoopAgent`, `K9PlanningLoopAgent` | SKILLS.md Skill 10 |
| `BaseCriticActorAgent` | `K9CriticActorAgent` | |
| `BaseIntentAgent` | `K9IntentAgent` | unknown `event_type` → `intent.in` |
| `BaseRulesAgent` | `K9RulesAgent` (rule → `hil` raises `RequiresHIL`) | evaluates through a `BaseRulesAdapter` |
| `BaseFormatterAgent` | `WebFormatterAgent` | |
| `BaseMCPAgent` | `WebSearchAgent`; `MCPClientAgent` is a stub | |
| `BaseIoTAgent` | `MQTTAgent` | |
| `BaseSecurityAgent` | (contract only) | |
| `BaseMessageAgent` | `QueueMessageAgent`, `TopicMessageAgent` | |
| `BaseLoggingAgent` | `ConsoleLoggingAgent`, `FileLoggingAgent`, `CloudLoggingAgent`, `LoggingAgent` | |
| `BaseAdapter` | `CrewAIOrchestratorAdapter`, `LangGraphOrchestratorAdapter`, `ClaudeAgentSDKOrchestratorAdapter` | wrap an existing crew/graph/SDK agent with K9 governance |

## Inference

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseLLM` | `OllamaLLM`, `OpenAILLM`, `AzureOpenAILLM`, `WatsonxLLM`, `K9XLiteLLMBridgeAdapter`, `MockLLM` | `LLMFactory`; agents call only `llm_invoke()` |
| `BaseProviderAdapter` | Ollama, OpenAI, Azure OpenAI, watsonx, Mock | `ProviderAdapterRegistry` |
| `BaseModelRouter` | `K9ModelRouter` (learned routing, eligibility first), `DefaultModelRouter` | `ModelRouterFactory` |
| `BaseEmbeddingService` | `OllamaEmbeddingService` | `EmbeddingServiceFactory` |
| `BasePromptEvaluator` | `K9PromptEvaluator` | `EvaluationFactory` |

## Governance and security

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseGovernance` | `ShieldGovernance` (via `governance_from_config`), `GuardianGovernance`, `ChainedGovernance`, `GovernanceAgent` | `GovernanceFactory`; every agent governed by construction |
| `BaseVulnerabilityCheck` | 15 Shield checks (list in CLAUDE.md) | `VulnerabilityChain`; catalog `k9_security/capabilities.yaml` |
| `BaseAttack` | (SATAN attacks live in `k9x_satan`) | `k9_security/attacks/`; one attack per check |
| `BaseZeroTrustGuard` | `DefaultZeroTrustGuard` | `BaseOrchestrator.apply_zero_trust()`; off unless `enable_zero_trust` |
| `BaseAuthorizationGuard` | `RoleBasedAuthorizationGuard` (action → roles) | |
| `BaseCompromiseGuard` | `PromptInjectionGuard` (weak substring match) | |
| `BaseDataLossGuard` | `SensitiveDataLossGuard` | |
| `BaseRiskEvaluator` | `ContextualRiskEvaluator` | |
| `BasePolicyEnforcer` | `RuntimePolicyEnforcer` | |
| `BaseAuthenticator` | `ApiKeyAuthenticator`, `OIDCAuthenticator` (`KeycloakAuthenticator`, `EntraIDAuthenticator`, `OktaAuthenticator`), `ChainedAuthenticator` | `AuthenticatorFactory`; `principal_type: agent` supported |
| `BaseIdentityResolver` | `PayloadIdentityResolver` (1.x default), `SignedIdentityResolver` | `security.identity.mode` |
| `BaseSecretManager` | `EnvSecretAdapter`, `VaultSecretAdapter` (HashiCorp Vault KV v2), `AwsSecretAdapter`, `IbmSecretAdapter` (IBM Secrets Manager) | `SecretManagerFactory`, `SecurityFactory` |
| (functions) | `@govern_tool_call`, `screen_tool_call`, `@govern_tool_result`, `screen_tool_result` | `k9_security/tool_result_guard.py` |

## Integration and tools

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseIntegrationAdapter` | (root of the adapter family) | `IntegrationAdapterFactory` |
| `BaseRulesAdapter` | `K9RulesAdapter` (YAML rules), `RestRulesAdapter` (decision service: ODM, Drools, ...) | rules themselves are SBB content |
| `BaseApiAdapter` | `HttpApiAdapter` | |
| `BaseDataAdapter` | `SqlDataAdapter` | |
| `BaseMessagingAdapter` | (contract only) | |
| `BaseBpmAdapter` | (contract only) | |
| `BaseWorkflowAdapter` | (contract only) | |
| `BaseProcessFlowAdapter` | (contract only) | |
| `BaseConnector` | `MCPStreamableHttpConnector`, `MCPHttpConnector` (REST only), `MCPStdioConnector`, `MCPClientConnector` | `MCPClientConnectionFactory`, `ConnectorFactory` |
| `BaseMCPServer` | `ContextMCPServer`, `MCPInferenceServer`; `OriginMCPServer` | `k9_mcp/servers/` |

## Context, streams and k9x Origin

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseEventFabric` | `KafkaEventFabric`, `InMemoryEventFabric` | `StreamsFactory` (refuses ungoverned streams in production) |
| `BaseEnvelopeMapper` | `AutoEnvelopeMapper`, `DebeziumEnvelopeMapper`, `LogLineEnvelopeMapper`, `NativeEnvelopeMapper` | `streams.mappers` |
| `BaseContextProjection` | (SBB implements) | |
| `BaseContextState` | `InMemoryContextState`, `RedisContextState` | |
| `BaseContextStream` | (contract only) | |
| `BaseContextWindow` | `InMemoryContextWindow` | |
| `BaseStreamProvider` | `RedpandaStreamProvider` | `StreamingFactory` |
| `BaseOrigin` | `K9Origin` (facts with provenance; no business decisions) | `OriginFactory`; `config/origin.yaml` |
| `BaseConflictRule` | `LateEventRule`, `TransitionRule` | |

## Retrieval and data

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseRetriever` | `K9Retriever` | `RetrieverFactory` |
| `BaseDocParser` | (SBB implements; `DoclingParser` is an agent) | |
| `BaseVectorDB` | `ChromaDBAdapter`, `MilvusAdapter`, `PgVectorAdapter`, `QdrantAdapter` | |

## Persistence, storage, cache, sessions, messaging

| ABB | OOB | Built by / where |
|---|---|---|
| `BasePersistence` | `MemoryPersistence`, `SQLitePersistence` | `PersistenceFactory` |
| `BaseDatabaseStorage` | `PostgresDatabaseStorage`, SQLite | `RoutingStateStore` (holds `hil_pending`) |
| `BaseStorage` | `LocalFileStorage` | |
| `BaseObjectStorage` | `S3ObjectStorageAdapter`, `IbmCosObjectStorageAdapter`, `LocalObjectStorageAdapter` | `ObjectStorageFactory`; large events travel as links |
| `BaseCache` | `InMemoryAdapter`, `RedisAdapter` | `CacheFactory` |
| `BaseSessionStore` | `InMemorySessionStore`, `SQLiteSessionStore`, `RedisSessionStore` | `SessionFactory`, `SessionRegistry` |
| `BaseQueue` | `LocalQueue` | `MessageFactory`; Kafka via `K9EventBus` (Router/Orchestrator only) |

## Observability, presentation, inspection

| ABB | OOB | Built by / where |
|---|---|---|
| `BaseMonitor` | `ConsoleMonitor`, `PrometheusMonitor`, `OTelMonitor`, `CloudWatchMonitor`, `MonitorServer` | `MonitorFactory` |
| `BaseUI` | `ConsoleUI`, `WebUI` | |
| `BaseInspectionRule` | K9-DEC-001/002, K9-KAF-001, `DirectModelAccessRule`, `EgressCoverageRule`, `AgentContractRule`, ... | `InspectionRuleRegistry`; `k9aif inspect` |
