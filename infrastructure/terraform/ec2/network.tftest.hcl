override_resource {
  override_during = plan
  target          = aws_eip.nat
  values          = { id = "eipalloc-test" }
}
override_resource {
  override_during = plan
  target          = aws_nat_gateway.this
  values          = { id = "nat-test" }
}
override_resource {
  override_during = plan
  target          = aws_subnet.this["public_a"]
  values          = { id = "subnet-public-a" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.alb
  values          = { id = "sg-alb" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.ec2
  values          = { id = "sg-ec2" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.rds
  values          = { id = "sg-rds" }
}
override_resource {
  override_during = plan
  target          = aws_route_table.public
  values          = { id = "rtb-public" }
}
override_resource {
  override_during = plan
  target          = aws_route_table.private
  values          = { id = "rtb-private" }
}
override_resource {
  override_during = plan
  target          = aws_internet_gateway.this
  values          = { id = "igw-test" }
}
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-south-1a", "ap-south-1b"] }
  }
}
variables {
  reviewed_ami_id     = "ami-0123456789abcdef0"
  postgres_version    = "17.1"
  expected_account_id = "123456789012"
  deployment_id       = "test-assessment"
  reviewer_ssh_cidr   = "192.0.2.1/32"
}
run "network" {
  command = plan
  assert {
    condition     = aws_vpc.this.enable_dns_support && aws_vpc.this.enable_dns_hostnames && aws_subnet.this["public_a"].cidr_block == "10.10.0.0/24" && aws_subnet.this["public_b"].cidr_block == "10.10.1.0/24" && aws_subnet.this["database_a"].cidr_block == "10.10.10.0/24" && aws_subnet.this["database_b"].cidr_block == "10.10.11.0/24"
    error_message = "Approved CIDRs and DNS settings must be preserved."
  }
  assert {
    condition     = aws_subnet.this["public_a"].availability_zone != aws_subnet.this["public_b"].availability_zone && aws_subnet.this["database_a"].availability_zone == aws_subnet.this["public_a"].availability_zone && aws_subnet.this["database_b"].availability_zone == aws_subnet.this["public_b"].availability_zone
    error_message = "Subnets must span two AZs."
  }
  assert {
    condition     = aws_route.internet.destination_cidr_block == "0.0.0.0/0" && aws_route.private_nat.destination_cidr_block == "0.0.0.0/0"
    error_message = "Private routing must use NAT, while public routing uses the IGW."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_http.cidr_ipv4 == "0.0.0.0/0" && length(aws_vpc_security_group_ingress_rule.ssh) == 0 && aws_vpc_security_group_ingress_rule.postgres.from_port == 5432 && aws_vpc_security_group_ingress_rule.ec2_http.from_port == 80
    error_message = "Ingress must match approved ports; SSH is closed by default."
  }
}
run "traffic_boundaries" {
  command = plan
  assert {
    condition     = aws_vpc_security_group_ingress_rule.ec2_http.referenced_security_group_id == "sg-alb" && aws_vpc_security_group_ingress_rule.postgres.referenced_security_group_id == "sg-ec2" && aws_vpc_security_group_egress_rule.postgres.referenced_security_group_id == "sg-rds" && aws_vpc_security_group_egress_rule.alb_http.referenced_security_group_id == "sg-ec2"
    error_message = "HTTP and database traffic must be restricted to the correct security groups."
  }
  assert {
    condition     = alltrue([for name, association in aws_route_table_association.this : association.route_table_id == (startswith(name, "public_") ? "rtb-public" : "rtb-private")]) && aws_route.internet.gateway_id == "igw-test" && aws_route.internet.route_table_id == "rtb-public"
    error_message = "Each subnet must use its intended route table and only public routes use the IGW."
  }
}
run "reviewer_ssh_enabled" {
  command = plan
  variables { enable_reviewer_ssh = true }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.ssh[0].cidr_ipv4 == "192.0.2.1/32" && aws_vpc_security_group_ingress_rule.ssh[0].from_port == 22 && aws_vpc_security_group_ingress_rule.ssh[0].to_port == 22
    error_message = "SSH must be opened only to the reviewer CIDR."
  }
}
run "unrestricted_ssh" {
  command = plan
  variables { reviewer_ssh_cidr = "0.0.0.0/0" }
  expect_failures = [var.reviewer_ssh_cidr]
}
run "invalid_network" {
  command = plan
  variables { vpc_cidr = "invalid" }
  expect_failures = [var.vpc_cidr]
}
run "invalid_region" {
  command = plan
  variables { aws_region = "us-east-1" }
  expect_failures = [var.aws_region]
}

run "nat_topology" {
  command = plan
  assert {
    condition     = aws_nat_gateway.this.subnet_id == aws_subnet.this["public_a"].id && aws_nat_gateway.this.allocation_id == aws_eip.nat.id && aws_route.private_nat.nat_gateway_id == aws_nat_gateway.this.id && aws_route.private_nat.route_table_id == "rtb-private"
    error_message = "One public-a NAT must route both private database subnets without public RDS access."
  }
}
