# Karpenter's upstream IAM/SQS/EventBridge template (karpenter/cloudformation.yaml),
# deployed by Terraform so `terraform apply` alone provisions it. Creates
# KarpenterNodeRole-<cluster>, the five KarpenterController*Policy-<cluster>
# managed policies, the <cluster> interruption queue and its EventBridge rules.
resource "aws_cloudformation_stack" "karpenter" {
  name          = "Karpenter-${local.cluster_name}"
  template_body = file("${path.module}/karpenter/cloudformation.yaml")
  parameters    = { ClusterName = local.cluster_name }
  capabilities  = ["CAPABILITY_NAMED_IAM"]
}

import {
  for_each = var.adopt_existing_resources ? toset(["Karpenter-${local.cluster_name}"]) : toset([])
  to       = aws_cloudformation_stack.karpenter
  id       = each.value
}

# Nodes launched by Karpenter join the cluster through this access entry.
resource "aws_eks_access_entry" "karpenter_nodes" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/KarpenterNodeRole-${local.cluster_name}"
  type          = "EC2_LINUX"
  depends_on    = [aws_cloudformation_stack.karpenter]
}

import {
  for_each = var.adopt_existing_resources ? toset(["${local.cluster_name}:arn:aws:iam::${var.expected_account_id}:role/KarpenterNodeRole-${local.cluster_name}"]) : toset([])
  to       = aws_eks_access_entry.karpenter_nodes
  id       = each.value
}
