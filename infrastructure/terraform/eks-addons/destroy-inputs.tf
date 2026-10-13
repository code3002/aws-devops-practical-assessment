# Read by the teardown executor (scripts/teardown) to run `terraform destroy`
# from an ephemeral CodeBuild environment without private tfvars files.
# Inputs only; no secret values are variables of this stack.
output "destroy_inputs" {
  value = {
    aws_region              = var.aws_region
    expected_account_id     = var.expected_account_id
    state_bucket            = var.state_bucket
    eks_state_key           = var.eks_state_key
    lbc_chart_version       = var.lbc_chart_version
    karpenter_chart_version = var.karpenter_chart_version
    strimzi_chart_version   = var.strimzi_chart_version
  }
}
