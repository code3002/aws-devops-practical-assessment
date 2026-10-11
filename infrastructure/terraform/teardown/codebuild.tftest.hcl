mock_provider "aws" {}
variables {
  DEPLOYMENT_ID         = "test-teardown"
  DEPLOYMENT_STARTED_AT = "2099-10-11T12:00:00Z"
  AWS_ACCOUNT_ID        = "123456789012"
  SOURCE_COMMIT_SHA     = "5890ed075b9a04b947ee87102a77da9d41be070b"
  BACKEND_BUCKET        = "test-assessment-state"
  LOCK_TABLE            = "test-assessment-locks"
}
run "project_configuration" {
  command = plan
  assert {
    condition     = aws_codebuild_project.destroy.source_version == var.SOURCE_COMMIT_SHA && aws_codebuild_project.destroy.source[0].type == "CODECOMMIT" && aws_codebuild_project.destroy.source[0].location == "https://git-codecommit.ap-south-1.amazonaws.com/v1/repos/aws-devops-practical-assessment" && aws_codebuild_project.destroy.source[0].buildspec == "infrastructure/terraform/teardown/executor/buildspec.yml" && aws_codebuild_project.destroy.environment[0].image == "aws/codebuild/standard:7.0" && aws_codebuild_project.destroy.build_timeout == 30 && aws_codebuild_project.destroy.queued_timeout == 15 && aws_codebuild_project.destroy.concurrent_build_limit == 1 && !aws_codebuild_project.destroy.environment[0].privileged_mode && aws_codebuild_project.destroy.artifacts[0].type == "NO_ARTIFACTS" && aws_cloudwatch_log_group.destroy.retention_in_days == 7
    error_message = "Project must use the pinned source and bounded non-privileged build configuration."
  }
  assert {
    condition     = { for e in aws_codebuild_project.destroy.environment[0].environment_variable : e.name => e.value } == local.build_environment
    error_message = "Explicit backend, region, deployment and preflight variables must reach the project."
  }
}
run "service_role_scope" {
  command = plan
  assert {
    condition     = jsondecode(aws_iam_role.destroy.assume_role_policy).Statement[0].Principal.Service == "codebuild.amazonaws.com" && jsondecode(aws_iam_role.destroy.assume_role_policy).Statement[0].Condition.StringEquals == { "aws:SourceAccount" = var.AWS_ACCOUNT_ID, "aws:SourceArn" = local.destroy_project_arn }
    error_message = "Build trust must be restricted to the approved account and project."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.destroy_foundation.policy).Statement == local.build_permissions.Statement && length(local.build_permissions.Statement) == 6 && local.build_permissions.Statement[1].Resource == "arn:aws:codecommit:ap-south-1:123456789012:aws-devops-practical-assessment" && local.build_permissions.Statement[0].Resource == "arn:aws:logs:ap-south-1:123456789012:log-group:/aws/codebuild/test-teardown-destroy:log-stream:*" && toset(local.build_permissions.Statement[4].Resource) == toset([for key in values(var.STATE_KEYS) : "arn:aws:s3:::test-assessment-state/${key}"]) && toset(flatten([for statement in jsondecode(aws_iam_role_policy.destroy_foundation.policy).Statement : statement.Action])) == toset(["logs:CreateLogStream", "logs:PutLogEvents", "codecommit:GitPull", "s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject", "dynamodb:DescribeTable"])
    error_message = "Backend/source/log permissions must remain within approved resources and read-only preflight actions."
  }
}
run "mutable_source_rejected" {
  command = plan
  variables { SOURCE_COMMIT_SHA = "main" }
  expect_failures = [var.SOURCE_COMMIT_SHA]
}
run "duplicate_state_keys_rejected" {
  command = plan
  variables {
    STATE_KEYS = { bootstrap = "bootstrap/terraform.tfstate", teardown = "bootstrap/terraform.tfstate", ec2 = "ec2/terraform.tfstate", eks = "eks/terraform.tfstate" }
  }
  expect_failures = [var.STATE_KEYS]
}
run "wildcard_state_key_rejected" {
  command = plan
  variables {
    STATE_KEYS = { bootstrap = "bootstrap/terraform.tfstate", teardown = "teardown/terraform.tfstate", ec2 = "*", eks = "eks/terraform.tfstate" }
  }
  expect_failures = [var.STATE_KEYS]
}

run "exact_workload_targets" {
  command = plan
  variables {
    EC2_INSTANCE_ID  = "i-0123456789abcdef0"
    EKS_CLUSTER_NAME = "test-assessment-eks"
  }
  assert {
    condition     = local.build_environment.EC2_INSTANCE_ID == var.EC2_INSTANCE_ID && local.build_environment.EKS_CLUSTER_NAME == var.EKS_CLUSTER_NAME
    error_message = "Explicit workload identities must reach the executor without discovery or wildcards."
  }
}
run "wildcard_cluster_rejected" {
  command = plan
  variables { EKS_CLUSTER_NAME = "*" }
  expect_failures = [var.EKS_CLUSTER_NAME]
}
run "wildcard_instance_rejected" {
  command = plan
  variables { EC2_INSTANCE_ID = "*" }
  expect_failures = [var.EC2_INSTANCE_ID]
}
