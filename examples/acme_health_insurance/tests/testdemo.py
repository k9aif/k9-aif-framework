# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  Acme Health Insurance Demo Runner
# Executes multiple flows sequentially to showcase event orchestration

import asyncio
import yaml

from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from examples.acme_health_insurance.orchestrators.acme_orchestrator import AcmeOrchestrator


async def run_demo():
    with open("examples/acme_health_insurance/config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    LLMFactory.bootstrap(config)

    orchestrator = AcmeOrchestrator(config=config)

    print("\nStarting Acme Health Insurance Experience Center demo...\n")

    print("Executing Health Plan Flow...")
    result = await orchestrator.execute_flow(
        {
            "intent": "health_plan",
            "member_id": "A12345",
            "question": "Am I eligible for the Gold Plan and what does preventive care include?"
        }
    )
    print(result)

    print("\nExecuting Claims Support Flow...")
    result = await orchestrator.execute_flow(
        {
            "intent": "claims_support",
            "message": "I want to submit a claim for CityCare Hospital visit. Claim ID C98765."
        }
    )
    print(result)

    print("\nExecuting Provider Lookup Flow...")
    result = await orchestrator.execute_flow(
        {
            "intent": "find_doctor",
            "question": "Find an in-network cardiologist near me."
        }
    )
    print(result)

    print("\nAll Acme flows completed.\n")


def main():
    asyncio.run(run_demo())


if __name__ == "__main__":
    try:
        main()
    finally:
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