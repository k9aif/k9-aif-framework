"""
ElasticMQ smoke-test consumer -- standalone, not wired into DAS.

Receives and prints messages from the same ElasticMQ queue queue_producer.py
sends to, proving real cross-process delivery through ElasticMQ (SQS-compatible
API), not just a script talking to itself. See queue_producer.py's docstring
for full context -- ElasticMQ isn't wired into DAS for anything yet; this is
purely an infrastructure smoke test.

Run (after queue_producer.py has sent at least one message, from the
k9-aif-framework repo root):
    python3 k9_aif_abb/tests/experiments/queue_consumer.py
"""
import json

import boto3

ENDPOINT = "http://192.168.1.98:9324"
QUEUE_NAME = "das-test-queue"


def main():
    sqs = boto3.client(
        "sqs",
        endpoint_url=ENDPOINT,
        region_name="elasticmq",
        aws_access_key_id="x",
        aws_secret_access_key="x",
    )

    queue_url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
    print(f"Queue URL: {queue_url}")
    print("Polling for messages (10s wait)...")

    resp = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=10,
    )
    messages = resp.get("Messages", [])

    if not messages:
        print("No messages available. Run queue_producer.py first.")
        return

    for msg in messages:
        body = json.loads(msg["Body"])
        print(f"\nReceived message_id={body.get('message_id')}")
        print(f"  sent_at: {body.get('sent_at')}")
        print(f"  text: {body.get('text')}")

        # Delete so it isn't redelivered -- real consumer behavior, not a peek.
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
        print("  (deleted from queue)")


if __name__ == "__main__":
    main()
