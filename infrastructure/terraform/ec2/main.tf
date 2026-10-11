data "aws_availability_zones" "available" {
  state = "available"
}
locals {
  subnet_numbers = { public_a = 0, public_b = 1, database_a = 10, database_b = 11 }
}
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.deployment_id}-ec2" }
}
resource "aws_subnet" "this" {
  for_each          = local.subnet_numbers
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value)
  availability_zone = data.aws_availability_zones.available.names[endswith(each.key, "_a") ? 0 : 1]
  # Assign a public address explicitly on the future EC2 instance.
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.deployment_id}-${each.key}" }
}
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
}
resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}
resource "aws_route_table" "private" {
  route  = []
  vpc_id = aws_vpc.this.id
}
resource "aws_route_table_association" "this" {
  for_each       = local.subnet_numbers
  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = startswith(each.key, "public_") ? aws_route_table.public.id : aws_route_table.private.id
}
