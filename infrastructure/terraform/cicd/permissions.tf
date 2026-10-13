resource "aws_iam_role_policy" "codebuild" {
  name = "${var.deployment_id}-app-build-permissions"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSource"
        Effect   = "Allow"
        Action   = ["codecommit:GitPull"]
        Resource = "arn:aws:codecommit:${var.aws_region}:${var.expected_account_id}:${var.codecommit_repository_name}"
      },
      {
        Sid    = "UploadArtifacts"
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "arn:aws:s3:::${local.artifact_bucket}/applications/*",
          "arn:aws:s3:::${local.artifact_bucket}/images/*"
        ]
      },
      {
        Sid    = "DeployToEC2"
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${var.expected_account_id}:document/${local.deployment_document}",
          "arn:aws:ec2:${var.aws_region}:${var.expected_account_id}:instance/${local.ec2_instance_id}"
        ]
      },
      {
        Sid      = "CheckDeployment"
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation"]
        Resource = "*"
      },
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PushPythonImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]
        Resource = aws_ecr_repository.python_time.arn
      },
      {
        Sid    = "WriteBuildLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.expected_account_id}:log-group:/aws/codebuild/${local.build_project_name}:log-stream:*"
      }
    ]
  })
}
