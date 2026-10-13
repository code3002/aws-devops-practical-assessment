data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "karpenter_pod_identity" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "karpenter_controller" {
  name               = "KarpenterController-${aws_eks_cluster.this.name}"
  assume_role_policy = data.aws_iam_policy_document.karpenter_pod_identity.json
}

resource "aws_iam_role_policy_attachment" "karpenter_controller" {
  for_each = toset([
    "KarpenterControllerNodeLifecyclePolicy",
    "KarpenterControllerIAMIntegrationPolicy",
    "KarpenterControllerEKSIntegrationPolicy",
    "KarpenterControllerInterruptionPolicy",
    "KarpenterControllerResourceDiscoveryPolicy"
  ])

  role       = aws_iam_role.karpenter_controller.name
  policy_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${each.value}-${aws_eks_cluster.this.name}"
  # The managed policies are created by the Karpenter CloudFormation stack.
  depends_on = [aws_cloudformation_stack.karpenter]
}

resource "aws_eks_pod_identity_association" "karpenter" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = "kube-system"
  service_account = "karpenter"
  role_arn        = aws_iam_role.karpenter_controller.arn
}
