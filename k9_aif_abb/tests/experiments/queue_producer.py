"""
ElasticMQ smoke-test producer -- standalone, not wired into DAS.

Sends one message to a real ElasticMQ queue (SQS-compatible API) running
in the podman container deployed 2026-09-03 (192.168.1.98:9324). Meant to
be run in a separate terminal/process from queue_consumer.py, so the two
prove real cross-process message delivery through ElasticMQ -- not just
one script sending to and reading from itself.

This does not touch DAS's actual pipeline or any framework code. ElasticMQ
is not currently wired into DAS for anything; this only confirms the
queue itself works, for whenever it does get wired in for real (a proper
BaseQueue implementation, following the same pattern as PgVectorAdapter --
see CLAUDE.md's "Everything is provisioned through factories").

Run (in one terminal, from the k9-aif-framework repo root):
    python3 k9_aif_abb/tests/experiments/queue_producer.py
Then, in another terminal:
    python3 k9_aif_abb/tests/experiments/queue_consumer.py
"""
import json
import sys
import uuid
from datetime import datetime, timezone

import boto3

ENDPOINT = "http://192.168.1.98:9324"
QUEUE_NAME = "das-test-queue"


def get_or_create_queue(sqs):
    try:
        return sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
    except sqs.exceptions.QueueDoesNotExist:
        print(f"Queue {QUEUE_NAME!r} doesn't exist yet -- creating it.")
        return sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]


def main():
    sqs = boto3.client(
        "sqs",
        endpoint_url=ENDPOINT,
        region_name="elasticmq",
        aws_access_key_id="x",
        aws_secret_access_key="x",
    )

    queue_url = get_or_create_queue(sqs)
    print(f"Queue URL: {queue_url}")

    message_id = str(uuid.uuid4())
    body = {
        "message_id": message_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "text": sys.argv[1] if len(sys.argv) > 1 else "Hello World!",
    }

    resp = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    print(f"Sent message_id={message_id}")
    print(f"  SQS MessageId: {resp['MessageId']}")
    print(f"  Body: {body}")
    print("\nRun queue_consumer.py (in another terminal, or after this one) to receive it.")


if __name__ == "__main__":
    main()
