mock_provider "aws" {}
variables {
  DEPLOYMENT_ID         = "test-teardown"
  SOURCE_COMMIT_SHA     = "5890ed075b9a04b947ee87102a77da9d41be070b"
  BACKEND_BUCKET        = "test-assessment-state"
  LOCK_TABLE            = "test-assessment-locks"
  DEPLOYMENT_STARTED_AT = "2099-10-11T12:00:00Z"
  AWS_ACCOUNT_ID        = "123456789012"
}
run "fixed_target" {
  command = plan
  assert {
    condition     = aws_scheduler_schedule.teardown.target[0].arn == "arn:aws:scheduler:::aws-sdk:codebuild:startBuild" && jsondecode(aws_scheduler_schedule.teardown.target[0].input) == { ProjectName = "test-teardown-destroy" }
    error_message = "Target must call StartBuild with only the approved project name."
  }
}
run "invalid_account" {
  command = plan
  variables { AWS_ACCOUNT_ID = "not-an-account" }
  expect_failures = [var.AWS_ACCOUNT_ID]
}
run "invalid_deployment_id" {
  command = plan
  variables { DEPLOYMENT_ID = "*" }
  expect_failures = [var.DEPLOYMENT_ID]
}
run "scoped_permissions" {
  command = plan
  assert {
    condition     = jsondecode(aws_iam_role_policy.start_destroy.policy).Statement == [{ Effect = "Allow", Action = "codebuild:StartBuild", Resource = local.destroy_project_arn }]
    error_message = "Scheduler must have only StartBuild on the specific project."
  }
  assert {
    condition     = jsondecode(aws_iam_role.scheduler.assume_role_policy).Statement == [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = var.AWS_ACCOUNT_ID, "aws:SourceArn" = "arn:aws:scheduler:ap-south-1:123456789012:schedule-group/test-teardown" } } }]
    error_message = "Trust must be limited to Scheduler, the intended account and exact group."
  }
}
run "disabled_resource" {
  command = plan
  variables {
    TEARDOWN_ENABLED      = false
    DEPLOYMENT_STARTED_AT = "2000-10-11T12:00:00Z"
  }
  assert {
    condition     = aws_scheduler_schedule.teardown.state == "DISABLED" && aws_scheduler_schedule.teardown.schedule_expression_timezone == "UTC" && aws_scheduler_schedule.teardown.flexible_time_window[0].mode == "OFF"
    error_message = "Cancellation must retain a disabled UTC schedule without a flexible window."
  }
}
