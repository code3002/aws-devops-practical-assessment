locals {
  source_repository_arn = "arn:aws:codecommit:ap-south-1:${var.AWS_ACCOUNT_ID}:aws-devops-practical-assessment"
  source_repository_url = "https://git-codecommit.ap-south-1.amazonaws.com/v1/repos/aws-devops-practical-assessment"
  build_log_arn         = "arn:aws:logs:ap-south-1:${var.AWS_ACCOUNT_ID}:log-group:/aws/codebuild/${local.destroy_project_name}"
  build_environment = merge({
    EXPECTED_ACCOUNT_ID    = var.AWS_ACCOUNT_ID
    AWS_REGION             = "ap-south-1"
    AWS_DEFAULT_REGION     = "ap-south-1"
    BACKEND_BUCKET         = var.BACKEND_BUCKET
    LOCK_TABLE             = var.LOCK_TABLE
    BOOTSTRAP_STATE_KEY    = var.STATE_KEYS.bootstrap
    TEARDOWN_STATE_KEY     = var.STATE_KEYS.teardown
    EC2_STATE_KEY          = var.STATE_KEYS.ec2
    EKS_STATE_KEY          = var.STATE_KEYS.eks
    DEPLOYMENT_ID          = var.DEPLOYMENT_ID
    EXPECTED_SOURCE_COMMIT = var.SOURCE_COMMIT_SHA
    EXECUTION_MODE         = "PREFLIGHT_ONLY"
    }, var.EC2_INSTANCE_ID == null ? {} : { EC2_INSTANCE_ID = var.EC2_INSTANCE_ID },
  var.EKS_CLUSTER_NAME == null ? {} : { EKS_CLUSTER_NAME = var.EKS_CLUSTER_NAME })
  build_permissions = {
    Version = "2012-10-17"
    Statement = [
      { Sid = "WriteProjectLogs", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.build_log_arn}:log-stream:*" },
      { Sid = "ReadApprovedSource", Effect = "Allow", Action = ["codecommit:GitPull"], Resource = local.source_repository_arn },
      { Sid = "BackendLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = "arn:aws:s3:::${var.BACKEND_BUCKET}" },
      { Sid = "ListApprovedStates", Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${var.BACKEND_BUCKET}", Condition = { StringEquals = { "s3:prefix" = values(var.STATE_KEYS) } } },
      { Sid = "ReadApprovedStates", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for key in values(var.STATE_KEYS) : "arn:aws:s3:::${var.BACKEND_BUCKET}/${key}"] },
      { Sid = "InspectLockTable", Effect = "Allow", Action = ["dynamodb:DescribeTable"], Resource = "arn:aws:dynamodb:ap-south-1:${var.AWS_ACCOUNT_ID}:table/${var.LOCK_TABLE}" },
    ]
  }
}
resource "aws_cloudwatch_log_group" "destroy" {
  tags              = local.deployment_tags
  name              = "/aws/codebuild/${local.destroy_project_name}"
  retention_in_days = 7
}
resource "aws_iam_role" "destroy" {
  tags = local.deployment_tags
  name = "${var.DEPLOYMENT_ID}-build"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.AWS_ACCOUNT_ID, "aws:SourceArn" = local.destroy_project_arn } }
    }]
  })
}
resource "aws_iam_role_policy" "destroy_foundation" {
  name   = "preflight-source-state-logs"
  role   = aws_iam_role.destroy.id
  policy = jsonencode(local.build_permissions)
}
resource "aws_codebuild_project" "destroy" {
  tags                   = local.deployment_tags
  name                   = local.destroy_project_name
  description            = "Non-destructive automatic teardown foundation; preflight only."
  service_role           = aws_iam_role.destroy.arn
  build_timeout          = 30
  queued_timeout         = 15
  concurrent_build_limit = 1
  source_version         = var.SOURCE_COMMIT_SHA
  source {
    type      = "CODECOMMIT"
    location  = local.source_repository_url
    buildspec = "infrastructure/terraform/teardown/executor/buildspec.yml"
  }
  artifacts {
    type = "NO_ARTIFACTS"
  }
  environment {
    type                        = "LINUX_CONTAINER"
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false
    dynamic "environment_variable" {
      for_each = local.build_environment
      content {
        name  = environment_variable.key
        value = environment_variable.value
        type  = "PLAINTEXT"
      }
    }
  }
  logs_config {
    cloudwatch_logs {
      status     = "ENABLED"
      group_name = aws_cloudwatch_log_group.destroy.name
    }
    s3_logs { status = "DISABLED" }
  }
  depends_on = [aws_iam_role_policy.destroy_foundation]
}
