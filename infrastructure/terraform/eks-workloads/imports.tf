# Live environment only: adopt objects that were created with kubectl, and the

# EKS DNS record previously owned by the route53 stack. No-ops for a fresh deployment.

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["Namespace/python-time"]]) : toset([])
  to       = kubernetes_manifest.namespace
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["StorageClass/gp3"]]) : toset([])
  to       = kubernetes_manifest.storage_class
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["EC2NodeClass/assessment"]]) : toset([])
  to       = kubernetes_manifest.ec2_node_class
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["NodePool/assessment"]]) : toset([])
  to       = kubernetes_manifest.node_pool
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["Deployment/python-time"]]) : toset([])
  to       = kubernetes_manifest.deployment
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["Service/python-time"]]) : toset([])
  to       = kubernetes_manifest.service
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["Gateway/python-time-gateway"]]) : toset([])
  to       = kubernetes_manifest.gateway
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["HTTPRoute/python-time-route"]]) : toset([])
  to       = kubernetes_manifest.http_route
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["KafkaNodePool/combined"]]) : toset([])
  to       = kubernetes_manifest.kafka_node_pool
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["Kafka/assessment-kafka"]]) : toset([])
  to       = kubernetes_manifest.kafka
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.import_id["KafkaTopic/assessment-events"]]) : toset([])
  to       = kubernetes_manifest.kafka_topic
  id       = each.value
}

import {
  for_each = { for key, doc in local.gateway_config : key => local.import_id[key] if var.adopt_existing_resources }
  to       = kubernetes_manifest.gateway_config[each.key]
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset(["${data.terraform_remote_state.route53.outputs.hosted_zone_id}_${var.eks_record_name}.${local.domain_name}_A"]) : toset([])
  to       = aws_route53_record.eks_app
  id       = each.value
}
