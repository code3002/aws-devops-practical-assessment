locals {
  k8s_dir = "${path.module}/../../kubernetes"

  # Gateway API standard channel (vendored upstream release; the version is in
  # each CRD's gateway.networking.k8s.io/bundle-version annotation) and the AWS
  # Load Balancer Controller Gateway CRDs. `status` is server-owned; strip it.
  crd_documents = concat(
    provider::kubernetes::manifest_decode_multi(file("${local.k8s_dir}/gateway-api/standard-install.yaml")),
    provider::kubernetes::manifest_decode_multi(file("${local.k8s_dir}/gateway-api/aws-gateway-crds.yaml")),
  )
  # key = kind/name; includes Gateway API's ValidatingAdmissionPolicy upgrade guard.
  crds = {
    for doc in local.crd_documents : "${doc.kind}/${doc.metadata.name}" => { for key, value in doc : key => value if key != "status" }
  }
}

resource "kubernetes_manifest" "crd" {
  for_each = local.crds
  manifest = each.value

  field_manager {
    # Adopted CRDs were created with kubectl; take over field ownership.
    force_conflicts = true
  }
}

import {
  for_each = { for key, doc in local.crds : key => "apiVersion=${doc.apiVersion},kind=${doc.kind},name=${doc.metadata.name}" if var.adopt_existing_resources }
  to       = kubernetes_manifest.crd[each.key]
  id       = each.value
}

# AWS Load Balancer Controller: reconciles the Gateway/HTTPRoute into an ALB.
# IAM role + Pod Identity association come from the eks stack.
resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.lbc_chart_version
  values = [templatefile("${local.k8s_dir}/aws-load-balancer-controller/values.yaml", {
    cluster_name = local.eks.cluster_name
    region       = var.aws_region
    vpc_id       = local.eks.reused_vpc_id
  })]
  wait       = true
  timeout    = 600
  depends_on = [kubernetes_manifest.crd]
}

# Karpenter controller on the system node group. Controller identity, node role
# and interruption queue come from the eks stack.
resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.karpenter_chart_version
  values = [yamlencode({
    # Sized for the small system node group; Pod Identity binds this service account.
    controller     = { resources = { requests = { cpu = "100m", memory = "256Mi" } } }
    serviceAccount = { name = "karpenter" }
    settings = {
      clusterName       = local.eks.cluster_name
      interruptionQueue = try(local.eks.karpenter_interruption_queue_name, local.eks.cluster_name)
    }
  })]
  wait    = true
  timeout = 600
}

# Strimzi Kafka operator (brief §2: Kafka via Helm using an operator).
resource "helm_release" "strimzi" {
  name             = "strimzi-kafka-operator"
  namespace        = "kafka"
  create_namespace = true
  repository       = "oci://quay.io/strimzi-helm"
  chart            = "strimzi-kafka-operator"
  version          = var.strimzi_chart_version
  values           = [yamlencode({ watchAnyNamespace = false })]
  wait             = true
  timeout          = 600
}

import {
  for_each = var.adopt_existing_resources ? toset(["kube-system/aws-load-balancer-controller"]) : toset([])
  to       = helm_release.aws_load_balancer_controller
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset(["kube-system/karpenter"]) : toset([])
  to       = helm_release.karpenter
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset(["kafka/strimzi-kafka-operator"]) : toset([])
  to       = helm_release.strimzi
  id       = each.value
}

output "cluster_name" { value = local.eks.cluster_name }
output "helm_releases" {
  value = {
    aws_load_balancer_controller = helm_release.aws_load_balancer_controller.metadata.version
    karpenter                    = helm_release.karpenter.metadata.version
    strimzi                      = helm_release.strimzi.metadata.version
  }
}
