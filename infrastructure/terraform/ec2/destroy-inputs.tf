# Read by the teardown executor (scripts/teardown) to run `terraform destroy`
# from an ephemeral CodeBuild environment without private tfvars files.
# Inputs only; no secret values are variables of this stack.
output "destroy_inputs" {
  value = {
    monitoring_interviewer_email    = var.monitoring_interviewer_email
    aws_region                      = var.aws_region
    expected_account_id             = var.expected_account_id
    deployment_id                   = var.deployment_id
    vpc_cidr                        = var.vpc_cidr
    reviewer_ssh_cidr               = var.reviewer_ssh_cidr
    reviewed_ami_id                 = var.reviewed_ami_id
    postgres_version                = var.postgres_version
    ssh_key_name                    = var.ssh_key_name
    artifact_bucket                 = var.artifact_bucket
    app_secret_arn                  = var.app_secret_arn
    ssm_document_name               = var.ssm_document_name
    enable_reviewer_ssh             = var.enable_reviewer_ssh
    manage_application_secret_value = var.manage_application_secret_value
  }
}
