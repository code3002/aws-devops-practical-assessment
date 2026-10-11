data "aws_ami" "reviewed" {
  owners = ["amazon"]
  filter {
    name   = "image-id"
    values = [var.reviewed_ami_id]
  }
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}
resource "aws_instance" "app" {
  ami                         = data.aws_ami.reviewed.id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.this["public_a"].id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  key_name                    = var.ssh_key_name
  user_data                   = file("${path.module}/../../../scripts/host/bootstrap.sh")
  user_data_replace_on_change = true
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    encrypted             = true
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }
  tags       = { Name = "${var.deployment_id}-app" }
  depends_on = [aws_route.internet, aws_route_table_association.this, aws_iam_role_policy_attachment.ssm, aws_iam_role_policy.runtime]
}
