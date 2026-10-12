#!/usr/bin/env bash
set -euo pipefail

helm upgrade --install strimzi-kafka-operator \
  oci://quay.io/strimzi-helm/strimzi-kafka-operator \
  --version 1.2.0 \
  --namespace kafka \
  --create-namespace \
  --set watchAnyNamespace=false \
  --wait \
  --timeout 5m

echo "=== Operator pods ==="
kubectl get pods -n kafka

echo "=== Kafka CRDs ==="
kubectl get crd \
  kafkas.kafka.strimzi.io \
  kafkanodepools.kafka.strimzi.io \
  kafkatopics.kafka.strimzi.io
