locals {
  destroy_project_name = "${var.DEPLOYMENT_ID}-destroy"
  destroy_project_arn  = "arn:aws:codebuild:ap-south-1:${var.AWS_ACCOUNT_ID}:project/${local.destroy_project_name}"
  trigger_function     = "${var.DEPLOYMENT_ID}-ttl-trigger"
  deployment_tags = {
    DeploymentId = var.DEPLOYMENT_ID
    ManagedBy    = "Terraform"
    Project      = "aws-devops-practical-assessment"
  }

  # Destroy order (brief §6): stop CI, remove Kubernetes-created AWS resources
  # (Gateway ALB, Karpenter nodes, Kafka volumes), add-ons, the cluster, DNS,
  # and finally the shared VPC with EC2/RDS.
  stack_order = [
    { stack = "cicd", key = var.STATE_KEYS.cicd },
    { stack = "eks-workloads", key = var.STATE_KEYS.eks_workloads },
    { stack = "eks-addons", key = var.STATE_KEYS.eks_addons },
    { stack = "eks", key = var.STATE_KEYS.eks },
    { stack = "route53", key = var.STATE_KEYS.route53 },
    { stack = "ec2", key = var.STATE_KEYS.ec2 },
  ]
}
