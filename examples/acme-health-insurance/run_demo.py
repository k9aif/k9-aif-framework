# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  Acme Health Insurance Demo Runner
# Executes multiple flows sequentially to showcase event orchestration

from k9_projects.acme_health_insurance.orchestrators.acme_orchestrator import AcmeOrchestrator


def main():
    orchestrator = AcmeOrchestrator()

    print("\n Starting Acme Health Insurance Experience Center demo...\n")

    # 1 Eligibility Check
    print("  Executing Eligibility Check Flow...")
    orchestrator.executeFlow({"intent": "eligibility_check", "member_id": "A12345"})

    # 2 Claim Processing
    print("\n  Executing Claim Processing Flow...")
    orchestrator.executeFlow({"intent": "claim_processing", "claim_id": "C98765"})

    # 3 Policy Advisor
    print("\n  Executing Policy Advisor Flow...")
    orchestrator.executeFlow({
        "intent": "policy_advice",
        "question": "What does preventive care include under the Gold Plan?"
    })

    print("\n All Acme flows completed.\n")

if __name__ == "__main__":
    try:
        main()
    finally:
        # Cleanly close any Kafka/Redpanda producer to prevent timeout warnings
        from kafka import KafkaProducer
        import kafka
        try:
            for ref in list(kafka.producer.kafka._PRODUCER_REFS):
                producer = ref()
                if producer:
                    producer.flush(timeout=2)
                    producer.close(timeout=2)
                    print("[INFO] Kafka producer closed cleanly.")
        except Exception:
            pass