data "archive_file" "trigger" {
  type        = "zip"
  source_file = "${path.module}/lambda/trigger.py"
  output_path = "${path.module}/.build/trigger.zip"
}

resource "aws_iam_role" "trigger" {
  tags = local.deployment_tags
  name = local.trigger_function
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "trigger" {
  name = "start-destroy-build"
  role = aws_iam_role.trigger.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "codebuild:StartBuild", Resource = local.destroy_project_arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.trigger.arn}:*" },
    ]
  })
}

resource "aws_cloudwatch_log_group" "trigger" {
  tags              = local.deployment_tags
  name              = "/aws/lambda/${local.trigger_function}"
  retention_in_days = 7
}

resource "aws_lambda_function" "trigger" {
  tags             = local.deployment_tags
  function_name    = local.trigger_function
  description      = "TTL trigger: starts the CodeBuild destroy project at the teardown deadline."
  role             = aws_iam_role.trigger.arn
  runtime          = "python3.13"
  handler          = "trigger.handler"
  filename         = data.archive_file.trigger.output_path
  source_code_hash = data.archive_file.trigger.output_base64sha256
  timeout          = 30
  environment {
    variables = {
      PROJECT_NAME = local.destroy_project_name
      DEADLINE     = formatdate("YYYY-MM-DD'T'hh:mm:ssZ", local.teardown_expires_at)
    }
  }
  depends_on = [aws_iam_role_policy.trigger, aws_cloudwatch_log_group.trigger]
}
