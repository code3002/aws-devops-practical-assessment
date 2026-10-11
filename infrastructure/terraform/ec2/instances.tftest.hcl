mock_provider "aws" {
  mock_data "aws_availability_zones" { defaults = { names = ["ap-south-1a", "ap-south-1b"] } }
  mock_data "aws_ami" { defaults = { id = "ami-0123456789abcdef0" } }
}
variables {
  expected_account_id = "123456789012"
  deployment_id       = "test-assessment"
  reviewer_ssh_cidr   = "192.0.2.1/32"
  reviewed_ami_id     = "ami-0123456789abcdef0"
  postgres_version    = "17.1"
}
override_resource {
  override_during = plan
  target          = aws_subnet.this["public_a"]
  values          = { id = "subnet-public-a" }
}
override_resource {
  override_during = plan
  target          = aws_subnet.this["public_b"]
  values          = { id = "subnet-public-b" }
}
override_resource {
  override_during = plan
  target          = aws_subnet.this["database_a"]
  values          = { id = "subnet-db-a" }
}
override_resource {
  override_during = plan
  target          = aws_subnet.this["database_b"]
  values          = { id = "subnet-db-b" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.ec2
  values          = { id = "sg-ec2" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.alb
  values          = { id = "sg-alb" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.rds
  values          = { id = "sg-rds" }
}
run "secure_compute" {
  command = plan
  assert {
    condition     = aws_instance.app.ami == var.reviewed_ami_id && aws_instance.app.instance_type == "t3.small" && aws_instance.app.subnet_id == "subnet-public-a" && aws_instance.app.associate_public_ip_address && aws_instance.app.vpc_security_group_ids == toset(["sg-ec2"])
    error_message = "Compute must use reviewed image and approved public placement."
  }
  assert {
    condition     = aws_instance.app.metadata_options[0].http_tokens == "required" && aws_instance.app.metadata_options[0].http_put_response_hop_limit == 1 && aws_instance.app.root_block_device[0].encrypted && aws_instance.app.root_block_device[0].volume_type == "gp3" && aws_instance.app.root_block_device[0].volume_size == 20 && aws_instance.app.root_block_device[0].delete_on_termination
    error_message = "IMDSv2 and disposable encrypted EBS are required."
  }
  assert {
    condition     = jsondecode(aws_iam_role.app.assume_role_policy).Statement[0].Principal.Service == "ec2.amazonaws.com" && aws_iam_role_policy_attachment.ssm.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" && aws_instance.app.iam_instance_profile == aws_iam_instance_profile.app.name && aws_iam_instance_profile.app.role == aws_iam_role.app.name
    error_message = "EC2 must receive only the dedicated SSM instance role."
  }
}
run "public_alb" {
  command = plan
  assert {
    condition     = !aws_lb.app.internal && aws_lb.app.load_balancer_type == "application" && aws_lb.app.subnets == toset(["subnet-public-a", "subnet-public-b"]) && aws_lb.app.security_groups == toset(["sg-alb"]) && !aws_lb.app.enable_deletion_protection
    error_message = "Public ALB must span the approved public subnets."
  }
  assert {
    condition     = aws_lb_target_group.app.target_type == "instance" && aws_lb_target_group.app.port == 80 && aws_lb_listener.http.port == 80 && aws_lb_listener.http.protocol == "HTTP" && aws_lb_target_group.app.health_check[0].path == "/health" && aws_lb_target_group.app.health_check[0].matcher == "200"
    error_message = "ALB must forward HTTP with the application health check."
  }
}
run "private_database" {
  command = plan
  assert {
    condition     = aws_db_instance.app.engine == "postgres" && aws_db_instance.app.engine_version == var.postgres_version && aws_db_instance.app.instance_class == "db.t4g.micro" && !aws_db_instance.app.publicly_accessible && !aws_db_instance.app.multi_az && aws_db_instance.app.availability_zone == "ap-south-1a" && aws_db_subnet_group.app.subnet_ids == toset(["subnet-db-a", "subnet-db-b"]) && aws_db_instance.app.vpc_security_group_ids == toset(["sg-rds"])
    error_message = "PostgreSQL must remain private and single-AZ with both DB subnets."
  }
  assert {
    condition     = aws_db_instance.app.manage_master_user_password && aws_db_instance.app.password == null && aws_db_instance.app.storage_encrypted && aws_db_instance.app.storage_type == "gp3" && aws_db_instance.app.allocated_storage == 20 && aws_db_instance.app.max_allocated_storage == 0
    error_message = "Use RDS-managed credentials and bounded encrypted gp3 storage."
  }
  assert {
    condition     = !aws_db_instance.app.deletion_protection && aws_db_instance.app.skip_final_snapshot && aws_db_instance.app.backup_retention_period == 0 && aws_db_instance.app.delete_automated_backups
    error_message = "Disposable cleanup must not retain database snapshots or backups."
  }
}
run "invalid_ami" {
  command = plan
  variables { reviewed_ami_id = "latest" }
  expect_failures = [var.reviewed_ami_id]
}
run "invalid_version" {
  command = plan
  variables { postgres_version = "17" }
  expect_failures = [var.postgres_version]
}
