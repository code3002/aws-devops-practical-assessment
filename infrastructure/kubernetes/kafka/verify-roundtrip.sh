#!/usr/bin/env bash
# Interviewer-side Kafka check (brief §2): describe the topic, produce a unique
# message and consume it back, all inside the cluster using the broker's CLI.
set -euo pipefail

namespace=kafka
pod=assessment-kafka-combined-0
topic=assessment-events
message="assessment-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"

kubectl -n "$namespace" wait kafka/assessment-kafka --for=condition=Ready --timeout=120s
kubectl -n "$namespace" exec "$pod" -- /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe --topic "$topic"

printf '%s\n' "$message" | kubectl -n "$namespace" exec -i "$pod" -- \
  /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic "$topic"
echo "Produced: $message"

if kubectl -n "$namespace" exec "$pod" -- /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic "$topic" --from-beginning --timeout-ms 20000 2>/dev/null |
  grep -Fxq "$message"; then
  echo "Consumed: $message"
  echo "PASS: Kafka topic round-trip"
else
  echo "FAIL: message not consumed" >&2
  exit 1
fi
