output "vpc_id" { value = aws_vpc.this.id }
output "subnet_ids" { value = { for name, subnet in aws_subnet.this : name => subnet.id } }
output "security_group_ids" {
  value = { alb = aws_security_group.alb.id, ec2 = aws_security_group.ec2.id, rds = aws_security_group.rds.id }
}
