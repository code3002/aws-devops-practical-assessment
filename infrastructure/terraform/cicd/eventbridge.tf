resource "aws_iam_role" "eventbridge_codebuild" {
  name = "${var.deployment_id}-eventbridge-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "events.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_codebuild" {
  name = "${var.deployment_id}-start-codebuild"
  role = aws_iam_role.eventbridge_codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "codebuild:StartBuild"
      Resource = aws_codebuild_project.app.arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "codecommit_main" {
  name        = "${var.deployment_id}-codecommit-main"
  description = "Start CodeBuild when CodeCommit ${var.source_branch} is updated"

  event_pattern = jsonencode({
    source        = ["aws.codecommit"]
    "detail-type" = ["CodeCommit Repository State Change"]
    resources = [
      "arn:aws:codecommit:${var.aws_region}:${var.expected_account_id}:${var.codecommit_repository_name}"
    ]
    detail = {
      event         = ["referenceCreated", "referenceUpdated"]
      referenceType = ["branch"]
      referenceName = [var.source_branch]
    }
  })
}

resource "aws_cloudwatch_event_target" "codebuild" {
  rule     = aws_cloudwatch_event_rule.codecommit_main.name
  arn      = aws_codebuild_project.app.arn
  role_arn = aws_iam_role.eventbridge_codebuild.arn

  depends_on = [
    aws_iam_role_policy.eventbridge_codebuild
  ]
}
