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
  count = 1
  name  = "${var.deployment_id}-runtime-read"
  role  = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObjectVersion"], Resource = [
        "arn:aws:s3:::${local.artifact_bucket_name}/applications/*",
        "arn:aws:s3:::${local.artifact_bucket_name}/images/*"
      ] },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [local.application_secret_arn, aws_db_instance.app.master_user_secret[0].secret_arn] }
    ]
  })
}
