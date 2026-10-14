# Jump server: a private t3.micro with kubectl and the SSM plugin, reached through an
# EC2 Instance Connect Endpoint. Reviewers connect with their reviewer access keys
# (`aws ec2-instance-connect ssh`), so no public IP, internet-facing port 22, SSH key
# or reviewer IP allow-list is needed. Inside the VPC it reaches the private EKS
# endpoint (cluster SG rule in the eks stack, jump_security_group_id).
locals {
  jump_name = "${var.deployment_id}-jump"
}

resource "aws_security_group" "jump_endpoint" {
  count  = var.create_jump_server ? 1 : 0
  name   = "${local.jump_name}-endpoint"
  vpc_id = aws_vpc.this.id
}

resource "aws_security_group" "jump" {
  count  = var.create_jump_server ? 1 : 0
  name   = local.jump_name
  vpc_id = aws_vpc.this.id
}

resource "aws_vpc_security_group_egress_rule" "jump_endpoint_ssh" {
  count                        = var.create_jump_server ? 1 : 0
  security_group_id            = aws_security_group.jump_endpoint[0].id
  referenced_security_group_id = aws_security_group.jump[0].id
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
}

# Port 22 only from the Instance Connect Endpoint, never from a CIDR.
resource "aws_vpc_security_group_ingress_rule" "jump_ssh" {
  count                        = var.create_jump_server ? 1 : 0
  security_group_id            = aws_security_group.jump[0].id
  referenced_security_group_id = aws_security_group.jump_endpoint[0].id
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
}

# HTTPS out through the NAT: AWS APIs, the EKS endpoint and tool downloads.
resource "aws_vpc_security_group_egress_rule" "jump_https" {
  count             = var.create_jump_server ? 1 : 0
  security_group_id = aws_security_group.jump[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_ec2_instance_connect_endpoint" "jump" {
  count              = var.create_jump_server ? 1 : 0
  subnet_id          = aws_subnet.this["database_a"].id
  security_group_ids = [aws_security_group.jump_endpoint[0].id]
  preserve_client_ip = false
  tags               = { Name = local.jump_name }
}

resource "aws_iam_role" "jump" {
  count = var.create_jump_server ? 1 : 0
  name  = local.jump_name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "jump_read_only" {
  count      = var.create_jump_server ? 1 : 0
  role       = aws_iam_role.jump[0].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "jump" {
  count  = var.create_jump_server ? 1 : 0
  name   = "${local.jump_name}-session"
  role   = aws_iam_role.jump[0].id
  policy = local.reviewer_session_policy
}

resource "aws_iam_instance_profile" "jump" {
  count = var.create_jump_server ? 1 : 0
  name  = local.jump_name
  role  = aws_iam_role.jump[0].name
}

resource "aws_instance" "jump" {
  count                       = var.create_jump_server ? 1 : 0
  ami                         = data.aws_ami.reviewed.id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.this["database_a"].id
  associate_public_ip_address = false
  vpc_security_group_ids      = [aws_security_group.jump[0].id]
  iam_instance_profile        = aws_iam_instance_profile.jump[0].name
  user_data = templatefile("${path.module}/../../../scripts/host/jump.sh.tftpl", {
    region             = var.aws_region
    cluster_name       = var.jump_eks_cluster_name
    app_instance_id    = aws_instance.app.id
    kubectl_version    = "v1.35.9"
    kubectl_sha256     = "3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb"
    ssm_plugin_version = "1.2.764.0"
    ssm_plugin_sha256  = "27ae57f75e625c39ab6b75a114508f6a2bc27d03a8d9eff92806cb37a7ee9170"
    kafka_check        = trimspace(file("${path.module}/../../kubernetes/kafka/verify-roundtrip.sh"))
  })
  user_data_replace_on_change = true
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    encrypted             = true
    volume_size           = 8
    volume_type           = "gp3"
    delete_on_termination = true
  }
  tags       = { Name = local.jump_name }
  depends_on = [aws_route.private_nat, aws_route_table_association.this]
}

# Reviewer: open the endpoint tunnel to port 22 and push a one-time key as ec2-user.
resource "aws_iam_role_policy" "reviewer_jump" {
  count = var.create_jump_server && var.create_reviewer_access ? 1 : 0
  name  = "${local.reviewer_name}-jump"
  role  = aws_iam_role.reviewer[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OpenTunnel"
        Effect    = "Allow"
        Action    = "ec2-instance-connect:OpenTunnel"
        Resource  = aws_ec2_instance_connect_endpoint.jump[0].arn
        Condition = { NumericEquals = { "ec2-instance-connect:remotePort" = "22" } }
      },
      {
        Sid       = "SendKey"
        Effect    = "Allow"
        Action    = "ec2-instance-connect:SendSSHPublicKey"
        Resource  = aws_instance.jump[0].arn
        Condition = { StringEquals = { "ec2:osuser" = "ec2-user" } }
      },
    ]
  })
}
