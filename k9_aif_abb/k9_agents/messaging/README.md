# messaging

Messaging agents: `MessageAgent`, the `QueueMessageAgent` and `TopicMessageAgent` bases, and
`KafkaAgent` (topic) and `SQSAgent` (queue). Kafka publishing in an application belongs to the
Router and Orchestrator, never to domain agents (see `CLAUDE.md`, Kafka ownership).
