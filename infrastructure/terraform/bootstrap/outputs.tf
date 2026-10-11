output "codecommit_clone_url_https" {
  description = "Authenticated HTTPS clone URL; configure the AWS CLI credential helper locally."
  value       = aws_codecommit_repository.mirror.clone_url_http
}
output "state_bucket_name" {
  value = aws_s3_bucket.state.id
}
output "lock_table_name" {
  value = aws_dynamodb_table.locks.name
}
output "aws_region" {
  value = var.aws_region
}
