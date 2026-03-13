# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending

from k9_aif_abb.k9_agents.messaging.topic_message_agent import TopicMessageAgent

class KafkaAgent(TopicMessageAgent):
    def __init__(self):
        super().__init__("KafkaAgent")

    def connect(self):
        print("[KafkaAgent] Connecting to Kafka broker (stubbed)")

    def close(self):
        print("[KafkaAgent] Closing Kafka connection (stubbed)")

    def publish(self, message: dict):
        print(f"[KafkaAgent] Publishing message to Kafka topic (stubbed): {message}")

    def subscribe(self, callback):
        print("[KafkaAgent] Subscribing to Kafka topic (stubbed)")
        # Simulate receiving one message and invoking callback
        callback({"body": "stubbed Kafka message"})