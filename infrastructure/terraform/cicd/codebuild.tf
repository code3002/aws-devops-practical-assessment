resource "aws_cloudwatch_log_group" "app_build" {
  name              = "/aws/codebuild/${local.build_project_name}"
  retention_in_days = 7
}

resource "aws_codebuild_project" "app" {
  source_version         = "main"
  name                   = local.build_project_name
  description            = "Build Docker image and deploy application to EC2"
  service_role           = aws_iam_role.codebuild.arn
  build_timeout          = 60
  queued_timeout         = 15
  concurrent_build_limit = 1

  source {
    type      = "CODECOMMIT"
    location  = "https://git-codecommit.${var.aws_region}.amazonaws.com/v1/repos/${var.codecommit_repository_name}"
    buildspec = "buildspec.yml"
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type                        = "LINUX_CONTAINER"
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "ARTIFACT_BUCKET"
      value = local.artifact_bucket
    }

    environment_variable {
      name  = "EC2_INSTANCE_ID"
      value = local.ec2_instance_id
    }

    environment_variable {
      name  = "DEPLOYMENT_DOCUMENT"
      value = local.deployment_document
    }

    environment_variable {
      name  = "EXPECTED_ACCOUNT_ID"
      value = var.expected_account_id
    }

    environment_variable {
      name  = "RDS_CA_SHA256"
      value = "ca4a9dc14e06c3f84274eff3ffed0e5d4d3463141593e1159eb4a0904df6cd74"
    }

    environment_variable {
      name  = "DATABASE_HOST"
      value = local.database_host
    }

    environment_variable {
      name  = "ADMIN_SECRET_ARN"
      value = local.admin_secret_arn
    }

    environment_variable {
      name  = "APP_SECRET_ARN"
      value = local.application_secret_arn
    }

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }
  }

  logs_config {
    cloudwatch_logs {
      status     = "ENABLED"
      group_name = aws_cloudwatch_log_group.app_build.name
    }
  }

  depends_on = [aws_iam_role_policy.codebuild]
}
