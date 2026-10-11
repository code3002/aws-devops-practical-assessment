resource "aws_iam_role" "app" {
  name = "${var.deployment_id}-ec2-ssm"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "app" {
  name = "${var.deployment_id}-ec2"
  role = aws_iam_role.app.name
}

# Initial setup needs both secrets; remove administrator access after initialization.
# No secret value, object upload or caller SSM permissions are granted here.
resource "aws_iam_role_policy" "runtime" {
  count = var.artifact_bucket != null || var.app_secret_arn != null ? 1 : 0
  name  = "${var.deployment_id}-runtime-read"
  role  = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      var.artifact_bucket == null ? [] : [{
        Effect = "Allow", Action = ["s3:GetObjectVersion"], Resource = ["arn:aws:s3:::${var.artifact_bucket}/applications/*"]
      }],
      var.app_secret_arn == null ? [] : [{
        Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.app_secret_arn, aws_db_instance.app.master_user_secret[0].secret_arn]
      }]
    )
  })
}
