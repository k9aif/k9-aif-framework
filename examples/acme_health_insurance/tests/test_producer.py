#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Test producer for Redpanda - publishes messages to acme-events topic
"""

from kafka import KafkaProducer
import json
import os
import time
from datetime import datetime

# Same variable as config/config.yaml (messaging); set it in .env, never hardcode an address.
BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")


def create_producer():
    """Create and configure Kafka producer"""
    producer = KafkaProducer(
        bootstrap_servers=[BROKER],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        key_serializer=lambda k: k.encode('utf-8') if k else None,
        acks='all',  # Wait for all replicas to acknowledge
        retries=3
    )
    return producer

def main():
    print(f"Connecting to Redpanda at {BROKER}...")
    
    producer = create_producer()
    topic = 'acme-events'
    
    print(f"Publishing messages to topic: {topic}")
    print("-" * 50)
    
    try:
        for i in range(10):
            # Create test message
            message = {
                'event_id': i,
                'event_type': 'test_event',
                'timestamp': datetime.now().isoformat(),
                'data': {
                    'message': f'Test message {i}',
                    'source': 'test_producer'
                }
            }
            
            # Send message
            key = f'key-{i}'
            future = producer.send(topic, key=key, value=message)
            
            # Wait for send to complete
            record_metadata = future.get(timeout=10)
            
            print(f"✓ Sent message {i}: partition={record_metadata.partition}, "
                  f"offset={record_metadata.offset}")
            
            time.sleep(1)  # Wait 1 second between messages
            
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        producer.flush()
        producer.close()
        print("-" * 50)
        print("Producer closed")

if __name__ == '__main__':
    main()
