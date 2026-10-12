output "cluster_name" { value = aws_eks_cluster.this.name }
output "cluster_endpoint" { value = aws_eks_cluster.this.endpoint }
output "cluster_security_group_id" { value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id }
output "node_role_arn" { value = aws_iam_role.nodes.arn }
output "reused_vpc_id" { value = data.aws_vpc.existing.id }
output "reused_private_subnet_ids" { value = var.private_subnet_ids }
