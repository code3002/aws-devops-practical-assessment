mock_provider "aws" {
  mock_data "aws_availability_zones" { defaults = { names = ["ap-south-1a", "ap-south-1b"] } }
  mock_data "aws_ami" { defaults = { id = "ami-0123456789abcdef0" } }
}
variables {
  expected_account_id = "123456789012"
  deployment_id       = "test-assessment"
  reviewer_ssh_cidr   = "192.0.2.1/32"
  reviewed_ami_id     = "ami-0123456789abcdef0"
  postgres_version    = "17.1"
}
run "private_artifacts_and_secret_metadata" {
  command = plan
  assert {
    condition     = aws_s3_bucket.artifacts[0].bucket == "test-assessment-123456789012-artifacts" && aws_s3_bucket.artifacts[0].force_destroy && aws_s3_bucket_public_access_block.artifacts[0].block_public_acls && aws_s3_bucket_public_access_block.artifacts[0].block_public_policy && aws_s3_bucket_public_access_block.artifacts[0].ignore_public_acls && aws_s3_bucket_public_access_block.artifacts[0].restrict_public_buckets && aws_s3_bucket_ownership_controls.artifacts[0].rule[0].object_ownership == "BucketOwnerEnforced" && aws_s3_bucket_versioning.artifacts[0].versioning_configuration[0].status == "Enabled"
    error_message = "Owned disposable artifacts must be private and versioned."
  }
  assert {
    condition     = aws_secretsmanager_secret.application[0].name == "test-assessment/application" && aws_secretsmanager_secret.application[0].recovery_window_in_days == 0
    error_message = "Only disposable application secret metadata belongs in Terraform."
  }
}
run "external_dependencies_not_owned" {
  command = plan
  variables {
    artifact_bucket = "external-artifacts"
    app_secret_arn  = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:external-test"
  }
  assert {
    condition     = length(aws_s3_bucket.artifacts) == 0 && length(aws_secretsmanager_secret.application) == 0 && output.artifact_bucket == "external-artifacts" && output.application_secret_arn == var.app_secret_arn
    error_message = "Explicit external dependencies must remain outside this stack's ownership."
  }
}
run "trusted_ssm_delivery" {
  command = plan
  assert {
    condition     = aws_ssm_document.deploy.document_type == "Command" && jsondecode(aws_ssm_document.deploy.content).parameters.Configuration.allowedPattern == "^[A-Za-z0-9+/=]+$" && contains(jsondecode(aws_ssm_document.deploy.content).mainSteps[0].inputs.runCommand, "python3 ${local.tools_directory}/deploy/prepare.py \"$work/config.json\"")
    error_message = "SSM must deliver pinned helpers and invoke the existing deployment coordinator safely."
  }
  assert {
    condition     = alltrue([for name in local.tool_files : contains(local.install_tools, "printf '%s  %s\\n' '${filesha256("${path.module}/../../../${name}")}' \"$work/file\" | sha256sum --check --status")])
    error_message = "Every installed helper must be checked against its reviewed source checksum."
  }
}
run "longest_bucket_name" {
  command = plan
  variables { deployment_id = "abcdefghijklmnopqrstuvwxyz12345678901234" }
  assert {
    condition     = length(aws_s3_bucket.artifacts[0].bucket) == 63
    error_message = "Maximum deployment ID must still produce a valid bucket length."
  }
}

run "ssm_document_name_avoids_reserved_prefix" {
  command = plan
  variables {
    deployment_id     = "aws-devops-test"
    ssm_document_name = null
  }
  assert {
    condition     = aws_ssm_document.deploy.name == "deploy-aws-devops-test"
    error_message = "Default SSM document names must not start with the reserved aws prefix."
  }
}

run "ssm_document_name_default" {
  command = plan
  variables {
    ssm_document_name = null
  }
  assert {
    condition     = aws_ssm_document.deploy.name == "test-assessment-app-deploy"
    error_message = "Non-reserved deployment IDs keep the <deployment_id>-app-deploy name."
  }
}

run "reserved_ssm_document_override_rejected" {
  command = plan
  variables {
    ssm_document_name = "aws-deploy"
  }
  expect_failures = [var.ssm_document_name]
}
