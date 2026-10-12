# Existing VPC and private subnets remain owned by EC2 Terraform state.
# These data sources perform read-only lookups; no network resource is created.
data "aws_vpc" "existing" {
  id = var.vpc_id
}
data "aws_subnet" "private" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
}
locals {
  cluster_name = "${var.deployment_id}-eks"
}
check "subnet_ownership" {
  assert {
    condition     = alltrue([for s in data.aws_subnet.private : s.vpc_id == data.aws_vpc.existing.id])
    error_message = "Every private subnet must belong to the selected VPC."
  }
  assert {
    condition     = length(distinct([for s in data.aws_subnet.private : s.availability_zone])) == 2
    error_message = "Private subnets must span two availability zones."
  }
}
