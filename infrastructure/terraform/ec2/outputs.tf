output "vpc_id" { value = aws_vpc.this.id }
output "subnet_ids" { value = { for name, subnet in aws_subnet.this : name => subnet.id } }
output "security_group_ids" {
  value = { alb = aws_security_group.alb.id, ec2 = aws_security_group.ec2.id, rds = aws_security_group.rds.id }
}

output "instance_id" { value = aws_instance.app.id }
output "instance_public_ip" { value = aws_instance.app.public_ip }
output "instance_role_arn" { value = aws_iam_role.app.arn }
output "alb_dns_name" { value = aws_lb.app.dns_name }
output "alb_zone_id" { value = aws_lb.app.zone_id }
output "alb_arn" { value = aws_lb.app.arn }
output "target_group_arn" { value = aws_lb_target_group.app.arn }
output "database_identifier" { value = aws_db_instance.app.identifier }
output "database_address" { value = aws_db_instance.app.address }
output "database_port" { value = aws_db_instance.app.port }
output "database_secret_arn" { value = aws_db_instance.app.master_user_secret[0].secret_arn }

output "artifact_bucket" { value = local.artifact_bucket_name }
output "application_secret_arn" { value = local.application_secret_arn }
output "nat_gateway_id" { value = aws_nat_gateway.this.id }
output "deployment_document_name" { value = aws_ssm_document.deploy.name }
output "deployment_document_version" { value = aws_ssm_document.deploy.document_version }
output "deployment_tools_sha256" { value = local.tools_sha256 }

output "reviewer_role_arn" { value = one(aws_iam_role.reviewer[*].arn) }
output "reviewer_user_name" { value = one(aws_iam_user.reviewer[*].name) }
output "reviewer_console_url" {
  value = var.create_reviewer_access ? "https://${var.expected_account_id}.signin.aws.amazon.com/console" : null
}
output "reviewer_switch_role_url" {
  value = var.create_reviewer_access ? "https://signin.aws.amazon.com/switchrole?account=${var.expected_account_id}&roleName=${local.reviewer_name}&displayName=reviewer" : null
}
output "reviewer_password" {
  value     = one(aws_iam_user_login_profile.reviewer[*].password)
  sensitive = true
}
output "reviewer_access_key_id" { value = one(aws_iam_access_key.reviewer[*].id) }
output "reviewer_secret_access_key" {
  value     = one(aws_iam_access_key.reviewer[*].secret)
  sensitive = true
}
