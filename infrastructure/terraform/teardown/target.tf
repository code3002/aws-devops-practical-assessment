locals {
  scheduler_group_arn = "arn:aws:scheduler:ap-south-1:${var.AWS_ACCOUNT_ID}:schedule-group/${var.DEPLOYMENT_ID}"
  scheduler_trust = {
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = {
        "aws:SourceAccount" = var.AWS_ACCOUNT_ID
        "aws:SourceArn"     = local.scheduler_group_arn
      } }
    }]
  }
  scheduler_permissions = {
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "codebuild:StartBuild"
      Resource = local.destroy_project_arn
    }]
  }
  scheduler_target = {
    arn   = "arn:aws:scheduler:::aws-sdk:codebuild:startBuild"
    input = jsonencode({ ProjectName = local.destroy_project_name })
  }
}

resource "aws_scheduler_schedule_group" "teardown" {
  tags = local.deployment_tags
  name = var.DEPLOYMENT_ID
}

resource "aws_iam_role" "scheduler" {
  tags               = local.deployment_tags
  name               = var.DEPLOYMENT_ID
  assume_role_policy = jsonencode(local.scheduler_trust)
}

resource "aws_iam_role_policy" "start_destroy" {
  name   = "start-approved-destroy"
  role   = aws_iam_role.scheduler.id
  policy = jsonencode(local.scheduler_permissions)
}

resource "aws_scheduler_schedule" "teardown" {
  name                         = var.DEPLOYMENT_ID
  group_name                   = aws_scheduler_schedule_group.teardown.name
  schedule_expression          = local.schedule_configuration.schedule_expression
  schedule_expression_timezone = local.schedule_configuration.schedule_expression_timezone
  state                        = local.schedule_configuration.state
  flexible_time_window {
    mode = local.schedule_configuration.flexible_time_window.mode
  }
  target {
    arn      = local.scheduler_target.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = local.scheduler_target.input
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 3
    }
  }
  depends_on = [aws_iam_role_policy.start_destroy, aws_codebuild_project.destroy]
  lifecycle {
    precondition {
      condition     = !var.TEARDOWN_ENABLED || timecmp(local.teardown_expires_at, timestamp()) > 0
      error_message = "Enabled deadline has expired at apply time. Replan with an intentional extension or disable teardown."
    }
  }
}

output "scheduler_target" {
  value = local.scheduler_target
}
