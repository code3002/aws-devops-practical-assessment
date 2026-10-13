output "cluster_name" { value = aws_eks_cluster.this.name }
output "cluster_endpoint" { value = aws_eks_cluster.this.endpoint }
output "cluster_certificate_authority_data" { value = aws_eks_cluster.this.certificate_authority[0].data }
output "cluster_security_group_id" { value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id }
output "node_role_arn" { value = aws_iam_role.nodes.arn }
output "reused_vpc_id" { value = data.aws_vpc.existing.id }
output "reused_private_subnet_ids" { value = var.private_subnet_ids }
output "aws_region" { value = var.aws_region }
output "karpenter_node_role_name" { value = "KarpenterNodeRole-${local.cluster_name}" }
output "karpenter_interruption_queue_name" { value = local.cluster_name }
output "lbc_role_arn" { value = aws_iam_role.lbc.arn }
output "kubectl_access_command" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.this.name}"
}
