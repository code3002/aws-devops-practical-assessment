locals {
  source_repository_arn = "arn:aws:codecommit:ap-south-1:${var.AWS_ACCOUNT_ID}:${var.CODECOMMIT_REPOSITORY}"
  source_repository_url = "https://git-codecommit.ap-south-1.amazonaws.com/v1/repos/${var.CODECOMMIT_REPOSITORY}"
  build_log_arn         = "arn:aws:logs:ap-south-1:${var.AWS_ACCOUNT_ID}:log-group:/aws/codebuild/${local.destroy_project_name}"

  # IAM resources the executor may delete: only names created for THIS deployment
  # (no account-wide prefixes, so other clusters' Karpenter roles stay out of scope).
  iam_account = "arn:aws:iam::${var.AWS_ACCOUNT_ID}"
  iam_resources = concat(
    flatten([for prefix in concat(["${var.EC2_DEPLOYMENT_ID}-", var.EKS_CLUSTER_NAME], var.EXTRA_IAM_NAME_PREFIXES) : [
      "${local.iam_account}:role/${prefix}*",
      "${local.iam_account}:policy/${prefix}*",
      "${local.iam_account}:instance-profile/${prefix}*",
    ]]),
    [
      "${local.iam_account}:role/KarpenterNodeRole-${var.EKS_CLUSTER_NAME}",
      "${local.iam_account}:role/KarpenterController-${var.EKS_CLUSTER_NAME}",
      "${local.iam_account}:policy/KarpenterController*Policy-${var.EKS_CLUSTER_NAME}",
    ],
  )
  # Never deletable by the executor: the executor itself and the shared backend.
  protected_roles = [
    "arn:aws:iam::${var.AWS_ACCOUNT_ID}:role/${var.DEPLOYMENT_ID}",
    "arn:aws:iam::${var.AWS_ACCOUNT_ID}:role/${var.DEPLOYMENT_ID}-build",
    "arn:aws:iam::${var.AWS_ACCOUNT_ID}:role/${local.trigger_function}",
  ]

  build_permissions = {
    Version = "2012-10-17"
    Statement = [
      { Sid = "WriteProjectLogs", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.build_log_arn}:log-stream:*" },
      { Sid = "ReadSource", Effect = "Allow", Action = ["codecommit:GitPull"], Resource = local.source_repository_arn },
      { Sid = "Identity", Effect = "Allow", Action = ["sts:GetCallerIdentity"], Resource = "*" },
      # Terraform S3 backend: read/write state objects and locks; never delete the bucket.
      { Sid = "StateBucket", Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"], Resource = "arn:aws:s3:::${var.BACKEND_BUCKET}" },
      { Sid = "StateObjects", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = [for key in values(var.STATE_KEYS) : "arn:aws:s3:::${var.BACKEND_BUCKET}/${key}"] },
      { Sid = "StateLocks", Effect = "Allow", Action = ["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"], Resource = "arn:aws:dynamodb:ap-south-1:${var.AWS_ACCOUNT_ID}:table/${var.LOCK_TABLE}" },
      # Destroy every regional resource the stacks created (brief §6). Scoped to the assessment region.
      {
        Sid    = "DestroyRegionalResources"
        Effect = "Allow"
        Action = [
          "autoscaling:*", "cloudformation:*", "cloudwatch:*", "codebuild:*", "ec2:*", "ecr:*", "eks:*",
          "elasticloadbalancing:*", "events:*", "logs:*", "rds:*", "secretsmanager:*", "sns:*", "sqs:*", "ssm:*",
          "s3:*", "kms:DescribeKey", "kms:ListAliases", "tag:GetResources",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = "ap-south-1" } }
      },
      { Sid = "DestroyDns", Effect = "Allow", Action = ["route53:*"], Resource = "*" },
      { Sid = "ReadIam", Effect = "Allow", Action = ["iam:Get*", "iam:List*"], Resource = "*" },
      { Sid = "DestroyProjectIam", Effect = "Allow", Action = ["iam:*"], Resource = local.iam_resources },
      # Explicit guards: backend, mirror, and the executor's own identities survive.
      {
        Sid      = "ProtectBackend"
        Effect   = "Deny"
        Action   = ["s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:PutBucketPolicy", "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = ["arn:aws:s3:::${var.BACKEND_BUCKET}", "arn:aws:s3:::${var.BACKEND_BUCKET}/*"]
      },
      { Sid = "ProtectLocks", Effect = "Deny", Action = ["dynamodb:DeleteTable", "dynamodb:UpdateTable"], Resource = "arn:aws:dynamodb:ap-south-1:${var.AWS_ACCOUNT_ID}:table/${var.LOCK_TABLE}" },
      { Sid = "ProtectMirror", Effect = "Deny", Action = ["codecommit:DeleteRepository"], Resource = local.source_repository_arn },
      { Sid = "ProtectExecutor", Effect = "Deny", Action = ["iam:*"], Resource = local.protected_roles },
      { Sid = "ProtectExecutorProject", Effect = "Deny", Action = ["codebuild:DeleteProject", "codebuild:UpdateProject"], Resource = local.destroy_project_arn },
    ]
  }
}

resource "aws_cloudwatch_log_group" "destroy" {
  tags              = local.deployment_tags
  name              = "/aws/codebuild/${local.destroy_project_name}"
  retention_in_days = 30
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
  name   = "preflight-source-state-logs" # name kept from the first version; now the ordered-destroy policy
  role   = aws_iam_role.destroy.id
  policy = jsonencode(local.build_permissions)
}

resource "aws_codebuild_project" "destroy" {
  tags                   = local.deployment_tags
  name                   = local.destroy_project_name
  description            = "Automatic teardown: ordered terraform destroy of every assessment stack (preflight unless EXECUTION_MODE=DESTROY)."
  service_role           = aws_iam_role.destroy.arn
  build_timeout          = 180
  queued_timeout         = 60
  concurrent_build_limit = 1
  source_version         = var.SOURCE_VERSION
  source {
    type      = "CODECOMMIT"
    location  = local.source_repository_url
    buildspec = "scripts/teardown/buildspec.yml"
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
      for_each = {
        EXPECTED_ACCOUNT_ID = var.AWS_ACCOUNT_ID
        AWS_REGION          = "ap-south-1"
        AWS_DEFAULT_REGION  = "ap-south-1"
        BACKEND_BUCKET      = var.BACKEND_BUCKET
        LOCK_TABLE          = var.LOCK_TABLE
        STACK_ORDER         = jsonencode(local.stack_order)
        EXECUTION_MODE      = var.EXECUTION_MODE
      }
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
