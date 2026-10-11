resource "aws_security_group" "alb" {
  name   = "${var.deployment_id}-alb"
  vpc_id = aws_vpc.this.id
}
resource "aws_security_group" "ec2" {
  name   = "${var.deployment_id}-ec2"
  vpc_id = aws_vpc.this.id
}
resource "aws_security_group" "rds" {
  name   = "${var.deployment_id}-rds"
  vpc_id = aws_vpc.this.id
}
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}
resource "aws_vpc_security_group_ingress_rule" "ec2_http" {
  security_group_id            = aws_security_group.ec2.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_vpc_security_group_ingress_rule" "ssh" {
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = var.reviewer_ssh_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}
resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.ec2.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "alb_http" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.ec2.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_vpc_security_group_egress_rule" "ec2_web" {
  for_each          = toset(["80", "443"])
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}
resource "aws_vpc_security_group_egress_rule" "postgres" {
  security_group_id            = aws_security_group.ec2.id
  referenced_security_group_id = aws_security_group.rds.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
