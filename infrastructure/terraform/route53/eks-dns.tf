# The EKS record now lives in infrastructure/terraform/eks-workloads, next to the
# Gateway whose ALB it points at. Forget it here without deleting the live record;
# eks-workloads imports it.
removed {
  from = aws_route53_record.eks_app

  lifecycle {
    destroy = false
  }
}
