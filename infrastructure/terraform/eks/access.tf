# Reviewer kubectl access (brief §2): `aws eks update-kubeconfig --name <cluster_name>`
# works for these principals once their IP is in cluster_public_access_cidrs.
resource "aws_eks_access_entry" "reviewer" {
  for_each      = toset(var.reviewer_principal_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "reviewer" {
  for_each      = toset(var.reviewer_principal_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.reviewer[each.key].principal_arn
  policy_arn    = var.reviewer_access_policy_arn

  access_scope {
    type = "cluster"
  }
}

# Auto-destroy (brief §6): the teardown CodeBuild role must delete the Gateway,
# Karpenter NodePool and Kafka through the Kubernetes API before the cluster goes.
resource "aws_eks_access_entry" "teardown" {
  count         = var.teardown_role_arn == null ? 0 : 1
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.teardown_role_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "teardown" {
  count         = var.teardown_role_arn == null ? 0 : 1
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.teardown[0].principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

# Jump server (ec2 stack) reaches the private cluster endpoint from inside the VPC.
resource "aws_vpc_security_group_ingress_rule" "jump_api" {
  count                        = var.jump_security_group_id == null ? 0 : 1
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = var.jump_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "kubectl from the reviewer jump server"
}
