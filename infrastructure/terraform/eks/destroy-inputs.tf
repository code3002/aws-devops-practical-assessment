# Read by the teardown executor (scripts/teardown) to run `terraform destroy`
# from an ephemeral CodeBuild environment without private tfvars files.
# Inputs only; no secret values are variables of this stack.
output "destroy_inputs" {
  value = {
    aws_region                               = var.aws_region
    expected_account_id                      = var.expected_account_id
    deployment_id                            = var.deployment_id
    vpc_id                                   = var.vpc_id
    private_subnet_ids                       = var.private_subnet_ids
    kubernetes_version                       = var.kubernetes_version
    cluster_public_access_cidrs              = var.cluster_public_access_cidrs
    node_instance_type                       = var.node_instance_type
    node_desired_size                        = var.node_desired_size
    lbc_iam_role_name                        = var.lbc_iam_role_name
    lbc_iam_policy_name                      = var.lbc_iam_policy_name
    existing_lbc_pod_identity_association_id = var.existing_lbc_pod_identity_association_id
    reviewer_principal_arns                  = var.reviewer_principal_arns
    reviewer_access_policy_arn               = var.reviewer_access_policy_arn
    jump_security_group_id                   = var.jump_security_group_id
  }
}
