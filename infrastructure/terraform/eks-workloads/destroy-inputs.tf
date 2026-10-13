# Read by the teardown executor (scripts/teardown) to run `terraform destroy`
# from an ephemeral CodeBuild environment without private tfvars files.
# Inputs only; no secret values are variables of this stack.
output "destroy_inputs" {
  value = {
    aws_region               = var.aws_region
    expected_account_id      = var.expected_account_id
    state_bucket             = var.state_bucket
    eks_state_key            = var.eks_state_key
    cicd_state_key           = var.cicd_state_key
    route53_state_key        = var.route53_state_key
    python_image_tag         = var.python_image_tag
    python_time_on_karpenter = var.python_time_on_karpenter
    eks_record_name          = var.eks_record_name
  }
}
