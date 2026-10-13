# AWS Load Balancer Controller identity (EKS Pod Identity). The policy is the
# upstream controller policy committed under infrastructure/kubernetes.
locals {
  lbc_role_name   = coalesce(var.lbc_iam_role_name, "${local.cluster_name}-alb-controller")
  lbc_policy_name = coalesce(var.lbc_iam_policy_name, "${local.cluster_name}-alb-controller")
  lbc_policy_arn  = "arn:aws:iam::${var.expected_account_id}:policy/${local.lbc_policy_name}"
}

resource "aws_iam_policy" "lbc" {
  name   = local.lbc_policy_name
  policy = file("${path.module}/../../kubernetes/aws-load-balancer-controller/iam-policy.json")
}

resource "aws_iam_role" "lbc" {
  name               = local.lbc_role_name
  assume_role_policy = file("${path.module}/../../kubernetes/aws-load-balancer-controller/trust-policy.json")
}

resource "aws_iam_role_policy_attachment" "lbc" {
  role       = aws_iam_role.lbc.name
  policy_arn = aws_iam_policy.lbc.arn
}

resource "aws_eks_pod_identity_association" "lbc" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.lbc.arn
}

import {
  for_each = var.adopt_existing_resources ? toset([local.lbc_policy_arn]) : toset([])
  to       = aws_iam_policy.lbc
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset([local.lbc_role_name]) : toset([])
  to       = aws_iam_role.lbc
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources ? toset(["${local.lbc_role_name}/${local.lbc_policy_arn}"]) : toset([])
  to       = aws_iam_role_policy_attachment.lbc
  id       = each.value
}

import {
  for_each = var.adopt_existing_resources && var.existing_lbc_pod_identity_association_id != null ? toset(["${local.cluster_name},${var.existing_lbc_pod_identity_association_id}"]) : toset([])
  to       = aws_eks_pod_identity_association.lbc
  id       = each.value
}
