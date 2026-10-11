# Existing explicitly supplied dependencies remain external and are never destroyed here.
locals {
  artifact_bucket_name   = var.artifact_bucket == null ? aws_s3_bucket.artifacts[0].id : var.artifact_bucket
  application_secret_arn = var.app_secret_arn == null ? aws_secretsmanager_secret.application[0].arn : var.app_secret_arn
}
resource "aws_s3_bucket" "artifacts" {
  count  = var.artifact_bucket == null ? 1 : 0
  bucket = "${var.deployment_id}-${var.expected_account_id}-artifacts"
  # Disposable application artifacts only; never use this for shared Terraform state.
  force_destroy = true
}
resource "aws_s3_bucket_public_access_block" "artifacts" {
  count                   = var.artifact_bucket == null ? 1 : 0
  bucket                  = aws_s3_bucket.artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "artifacts" {
  count  = var.artifact_bucket == null ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  count  = var.artifact_bucket == null ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "artifacts" {
  count  = var.artifact_bucket == null ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_policy" "artifacts" {
  count  = var.artifact_bucket == null ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.artifacts[0].arn, "${aws_s3_bucket.artifacts[0].arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
# Metadata only: populate through the approved runtime procedure, never secret_version.
resource "aws_secretsmanager_secret" "application" {
  count                   = var.app_secret_arn == null ? 1 : 0
  name                    = "${var.deployment_id}/application"
  recovery_window_in_days = 0
}
