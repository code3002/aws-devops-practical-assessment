# Read by the teardown executor (scripts/teardown) to run `terraform destroy`
# from an ephemeral CodeBuild environment without private tfvars files.
# Inputs only; no secret values are variables of this stack.
output "destroy_inputs" {
  value = {
    aws_region                 = var.aws_region
    expected_account_id        = var.expected_account_id
    deployment_id              = var.deployment_id
    state_bucket               = var.state_bucket
    ec2_state_key              = var.ec2_state_key
    codecommit_repository_name = var.codecommit_repository_name
    python_ecr_repository_name = var.python_ecr_repository_name
  }
}
