# Kubernetes workloads rendered from the manifests committed in the repository.
# Applied after eks-addons, so every CRD exists when these are planned.
locals {
  k8s_dir = "${path.module}/../../kubernetes"

  # Names are deterministic; outputs are preferred when the upstream state has them.
  python_repository = try(data.terraform_remote_state.cicd.outputs.python_ecr_repository_url,
  "${var.expected_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/eks-python-time")
  python_image = "${local.python_repository}:${var.python_image_tag}"
  domain_name  = trimsuffix(data.aws_route53_zone.assessment.name, ".")

  # key = kind/name; every committed document is applied as-is (status stripped).
  decode = {
    for name, path in {
      namespace   = "${path.module}/../../../kubernetes/python-time/namespace.yaml"
      storage     = "${local.k8s_dir}/storage/gp3.yaml"
      gateway     = "${local.k8s_dir}/gateway-api/python-time-gateway.yaml"
      targetgroup = "${local.k8s_dir}/gateway-api/python-time-targetgroup.yaml"
      kafka       = "${local.k8s_dir}/kafka/kafka.yaml"
    } : name => { for doc in provider::kubernetes::manifest_decode_multi(file(path)) : "${doc.kind}/${doc.metadata.name}" => doc }
  }
  app = { for doc in provider::kubernetes::manifest_decode_multi(templatefile("${path.module}/../../../kubernetes/python-time/deployment.yaml", {
    image              = local.python_image
    on_karpenter       = var.python_time_on_karpenter
    karpenter_nodepool = "assessment"
  })) : "${doc.kind}/${doc.metadata.name}" => doc }
  karpenter = { for doc in provider::kubernetes::manifest_decode_multi(templatefile("${path.module}/../eks/karpenter/manifests/provisioning.yaml", {
    node_role_name    = try(local.eks.karpenter_node_role_name, "KarpenterNodeRole-${local.eks.cluster_name}")
    subnet_ids        = local.eks.reused_private_subnet_ids
    security_group_id = local.eks.cluster_security_group_id
  })) : "${doc.kind}/${doc.metadata.name}" => doc }

  gateway_config = {
    for key, doc in merge(local.decode.gateway, local.decode.targetgroup) : key => doc
    if contains(["LoadBalancerConfiguration", "TargetGroupConfiguration", "GatewayClass"], doc.kind)
  }

  # Import IDs for adopting objects created with kubectl (live environment).
  import_id = { for key, doc in merge(
    local.decode.namespace, local.decode.storage, local.decode.gateway, local.decode.targetgroup,
    local.decode.kafka, local.app, local.karpenter) :
    key => join(",", compact([
      "apiVersion=${doc.apiVersion}", "kind=${doc.kind}",
      try("namespace=${doc.metadata.namespace}", ""), "name=${doc.metadata.name}"
    ]))
  }
}

# --- Namespace and storage ---------------------------------------------------
resource "kubernetes_manifest" "namespace" {
  manifest = local.decode.namespace["Namespace/python-time"]
  field_manager { force_conflicts = true }
}

resource "kubernetes_manifest" "storage_class" {
  manifest = local.decode.storage["StorageClass/gp3"]
  field_manager { force_conflicts = true }
}

# --- Karpenter: t3.medium-only workload capacity -------------------------------
resource "kubernetes_manifest" "ec2_node_class" {
  manifest = local.karpenter["EC2NodeClass/assessment"]
  field_manager { force_conflicts = true }
  timeouts {
    delete = "20m"
  }
}

resource "kubernetes_manifest" "node_pool" {
  manifest = local.karpenter["NodePool/assessment"]
  field_manager { force_conflicts = true }
  # Destroy order: NodePool first, then EC2NodeClass, whose finalizer waits
  # until Karpenter has terminated every node it launched.
  depends_on = [kubernetes_manifest.ec2_node_class]
}

# --- Python application -------------------------------------------------------
resource "kubernetes_manifest" "deployment" {
  manifest = local.app["Deployment/python-time"]
  field_manager { force_conflicts = true }
  wait {
    rollout = true
  }
  timeouts {
    create = "15m"
    update = "15m"
  }
  # Workload pods are removed before Karpenter capacity on destroy.
  depends_on = [kubernetes_manifest.namespace, kubernetes_manifest.node_pool]
}

resource "kubernetes_manifest" "service" {
  manifest = local.app["Service/python-time"]
  field_manager { force_conflicts = true }
  depends_on = [kubernetes_manifest.namespace]
}

# --- Gateway API (AWS Load Balancer Controller provisions the ALB) -------------
resource "kubernetes_manifest" "gateway_config" {
  for_each = local.gateway_config
  manifest = each.value
  field_manager { force_conflicts = true }
  depends_on = [kubernetes_manifest.namespace, kubernetes_manifest.service]
}

resource "kubernetes_manifest" "gateway" {
  manifest = local.decode.gateway["Gateway/python-time-gateway"]
  field_manager { force_conflicts = true }
  wait {
    condition {
      type   = "Programmed"
      status = "True"
    }
  }
  timeouts {
    create = "15m"
    delete = "15m"
  }
  depends_on = [kubernetes_manifest.gateway_config]
}

resource "kubernetes_manifest" "http_route" {
  manifest = local.decode.gateway["HTTPRoute/python-time-route"]
  field_manager { force_conflicts = true }
  depends_on = [kubernetes_manifest.gateway, kubernetes_manifest.service]
}

data "kubernetes_resource" "gateway" {
  api_version = "gateway.networking.k8s.io/v1"
  kind        = "Gateway"
  metadata {
    name      = "python-time-gateway"
    namespace = "python-time"
  }
  depends_on = [kubernetes_manifest.gateway]
}

data "aws_lb_hosted_zone_id" "alb" {}

data "aws_route53_zone" "assessment" {
  zone_id = data.terraform_remote_state.route53.outputs.hosted_zone_id
}

# Brief §2: DNS name resolving to the Gateway's provisioned ALB.
resource "aws_route53_record" "eks_app" {
  zone_id = data.terraform_remote_state.route53.outputs.hosted_zone_id
  name    = "${var.eks_record_name}.${local.domain_name}"
  type    = "A"

  alias {
    name                   = data.kubernetes_resource.gateway.object.status.addresses[0].value
    zone_id                = data.aws_lb_hosted_zone_id.alb.id
    evaluate_target_health = false
  }
}

# --- Kafka (Strimzi, KRaft) ---------------------------------------------------
resource "kubernetes_manifest" "kafka_node_pool" {
  manifest = local.decode.kafka["KafkaNodePool/combined"]
  field_manager { force_conflicts = true }
  depends_on = [kubernetes_manifest.storage_class]
}

resource "kubernetes_manifest" "kafka" {
  manifest = local.decode.kafka["Kafka/assessment-kafka"]
  field_manager { force_conflicts = true }
  wait {
    condition {
      type   = "Ready"
      status = "True"
    }
  }
  timeouts {
    create = "20m"
    delete = "15m"
  }
  depends_on = [kubernetes_manifest.kafka_node_pool]
}

resource "kubernetes_manifest" "kafka_topic" {
  manifest = local.decode.kafka["KafkaTopic/assessment-events"]
  field_manager { force_conflicts = true }
  depends_on = [kubernetes_manifest.kafka]
}
