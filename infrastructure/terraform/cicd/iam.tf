locals {
  build_project_name = "${var.deployment_id}-app-build"
  build_project_arn  = "arn:aws:codebuild:${var.aws_region}:${var.expected_account_id}:project/${local.build_project_name}"
}

resource "aws_iam_role" "codebuild" {
  name = "${var.deployment_id}-app-codebuild-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "codebuild.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = var.expected_account_id
          "aws:SourceArn"     = local.build_project_arn
        }
      }
    }]
  })
}
