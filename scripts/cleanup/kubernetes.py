"""Ordered cleanup of Kubernetes-owned resources before Terraform destroys EKS."""
import json
import os
import subprocess
import time

import ec2

NAMESPACE = "python-time"
KAFKA_NAMESPACE = "kafka"
GATEWAY = "python-time-gateway"
HTTP_ROUTE = "python-time-route"
KAFKA_CLUSTER = "assessment-kafka"
KAFKA_TOPIC = "assessment-events"
STRIMZI_RELEASE = "strimzi-kafka-operator"


def command(args, input_text=None):
    environment = os.environ | {"AWS_PAGER": ""}
    result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                            env=environment, timeout=900)
    if result.returncode:
        raise ec2.CleanupError("Kubernetes cleanup command failed: " + args[0])
    return result.stdout


def resource_exists(kind, name, namespace):
    result = subprocess.run(
        ["kubectl", "get", kind, name, "--namespace", namespace,
         "--ignore-not-found", "--output", "json"],
        capture_output=True, text=True, env=os.environ | {"AWS_PAGER": ""}, timeout=120)
    if result.returncode:
        raise ec2.CleanupError("Could not inspect Kubernetes resource: " + kind)
    return bool(result.stdout.strip()) and json.loads(result.stdout).get("metadata", {}).get("name") == name


def wait_absent(kind, name, namespace, attempts=30):
    for _ in range(attempts):
        if not resource_exists(kind, name, namespace):
            return
        time.sleep(2)
    raise ec2.CleanupError(f"Kubernetes resource remains: {namespace}/{kind}/{name}")


def wait_load_balancers_absent(region, addresses, attempts=30):
    if not addresses:
        return
    for _ in range(attempts):
        result = json.loads(command([
            "aws", "elbv2", "describe-load-balancers", "--region", region,
            "--query", "LoadBalancers[?DNSName==`" + "` || DNSName==`".join(addresses) + "`].DNSName",
            "--output", "json",
        ]))
        if not result:
            return
        time.sleep(2)
    raise ec2.CleanupError("Gateway-owned load balancer remains")


def cluster_is_active(region, cluster):
    result = subprocess.run(
        ["aws", "eks", "describe-cluster", "--region", region, "--name", cluster,
         "--query", "cluster.status", "--output", "text"],
        capture_output=True, text=True, env=os.environ | {"AWS_PAGER": ""}, timeout=120)
    if result.returncode:
        raise ec2.CleanupError("Could not inspect EKS cluster")
    return result.stdout.strip() == "ACTIVE"


def cleanup(region, cluster, execute=False):
    ec2.check(region == "ap-south-1", "Unsupported cleanup region")
    ec2.check(cluster and cluster_is_active(region, cluster), "EKS cluster is not active")
    gateway = json.loads(command(["kubectl", "get", "gateway", GATEWAY, "--namespace", NAMESPACE, "--output", "json"]))
    gateway_addresses = [address["value"] for address in gateway.get("status", {}).get("addresses", [])
                         if address.get("value")]
    command(["kubectl", "get", "kafka", KAFKA_CLUSTER, "--namespace", KAFKA_NAMESPACE, "--output", "json"])
    if not execute:
        print("DRY RUN: Kubernetes Gateway, Kafka topic and Kafka cluster require ordered cleanup.")
        return

    command(["kubectl", "delete", "httproute", HTTP_ROUTE, "--namespace", NAMESPACE,
             "--ignore-not-found", "--wait=true"])
    command(["kubectl", "delete", "gateway", GATEWAY, "--namespace", NAMESPACE,
             "--ignore-not-found", "--wait=true"])
    wait_absent("gateway", GATEWAY, NAMESPACE)
    wait_load_balancers_absent(region, gateway_addresses)

    command(["kubectl", "delete", "kafkatopic", KAFKA_TOPIC, "--namespace", KAFKA_NAMESPACE,
             "--ignore-not-found", "--wait=true"])
    command(["kubectl", "delete", "kafka", KAFKA_CLUSTER, "--namespace", KAFKA_NAMESPACE,
             "--ignore-not-found", "--wait=true"])
    wait_absent("kafka", KAFKA_CLUSTER, KAFKA_NAMESPACE)

    release = subprocess.run(["helm", "status", STRIMZI_RELEASE, "--namespace", KAFKA_NAMESPACE],
                             capture_output=True, text=True, env=os.environ | {"AWS_PAGER": ""}, timeout=120)
    if release.returncode == 0:
        command(["helm", "uninstall", STRIMZI_RELEASE, "--namespace", KAFKA_NAMESPACE,
                 "--wait", "--timeout", "10m"])
    print("Kubernetes Gateway/HTTPRoute, Gateway ALB, Kafka topic/cluster and operator cleanup completed.")
