resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "eks-pod-identity-agent"

  tags = {
    Component = "eks"
  }

  depends_on = [
    aws_eks_node_group.system
  ]
}
