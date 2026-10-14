# Reviewer access: an IAM user whose only permission is to assume a read-only
# reviewer role. The role views every resource in the console/CLI, opens SSM
# sessions to the app instance, connects to the jump server (jump.tf) and gets kubectl access
# through an EKS access entry (eks stack, reviewer_principal_arns).
# Names start with "<deployment_id>-", so the teardown executor deletes them too.
locals {
  reviewer_name = "${var.deployment_id}-reviewer"

  # Shared by the reviewer role and the jump server role.
  reviewer_session_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Shell or port forwarding (Prometheus :9090) on the app instance only.
      {
        Sid      = "SessionToAppInstance"
        Effect   = "Allow"
        Action   = ["ssm:StartSession"]
        Resource = aws_instance.app.arn
      },
      {
        Sid    = "SessionDocuments"
        Effect = "Allow"
        Action = ["ssm:StartSession"]
        Resource = [
          "arn:aws:ssm:${var.aws_region}::document/AWS-StartPortForwardingSession",
          "arn:aws:ssm:${var.aws_region}:${var.expected_account_id}:document/SSM-SessionManagerRunShell",
        ]
      },
      {
        Sid      = "OwnSessions"
        Effect   = "Allow"
        Action   = ["ssm:TerminateSession", "ssm:ResumeSession"]
        Resource = "arn:aws:ssm:${var.aws_region}:${var.expected_account_id}:session/*"
      },
      # ReadOnlyAccess allows s3:GetObject; object contents (Terraform state,
      # deployment artifacts) are not needed to review the infrastructure.
      {
        Sid      = "NoObjectContents"
        Effect   = "Deny"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role" "reviewer" {
  count = var.create_reviewer_access ? 1 : 0
  name  = local.reviewer_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${var.expected_account_id}:root" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:PrincipalArn" = "arn:aws:iam::${var.expected_account_id}:user/${local.reviewer_name}" } }
    }]
  })
  max_session_duration = 43200
}

resource "aws_iam_role_policy_attachment" "reviewer_read_only" {
  count      = var.create_reviewer_access ? 1 : 0
  role       = aws_iam_role.reviewer[0].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "reviewer" {
  count  = var.create_reviewer_access ? 1 : 0
  name   = "${local.reviewer_name}-session"
  role   = aws_iam_role.reviewer[0].id
  policy = local.reviewer_session_policy
}

resource "aws_iam_user" "reviewer" {
  count         = var.create_reviewer_access ? 1 : 0
  name          = local.reviewer_name
  force_destroy = true
}

resource "aws_iam_user_policy" "reviewer" {
  count = var.create_reviewer_access ? 1 : 0
  name  = "${local.reviewer_name}-assume"
  user  = aws_iam_user.reviewer[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "AssumeReviewerRole", Effect = "Allow", Action = "sts:AssumeRole", Resource = aws_iam_role.reviewer[0].arn },
      { Sid = "Identity", Effect = "Allow", Action = "sts:GetCallerIdentity", Resource = "*" },
      { Sid = "OwnPassword", Effect = "Allow", Action = ["iam:ChangePassword", "iam:GetUser"], Resource = aws_iam_user.reviewer[0].arn },
      { Sid = "PasswordPolicy", Effect = "Allow", Action = "iam:GetAccountPasswordPolicy", Resource = "*" },
    ]
  })
}

# The generated password and access key are kept only in the encrypted remote
# state and read with `terraform output -raw`; they are never committed.
resource "aws_iam_user_login_profile" "reviewer" {
  count                   = var.create_reviewer_access ? 1 : 0
  user                    = aws_iam_user.reviewer[0].name
  password_length         = 24
  password_reset_required = false
}

resource "aws_iam_access_key" "reviewer" {
  count = var.create_reviewer_access ? 1 : 0
  user  = aws_iam_user.reviewer[0].name
}
