terraform {
  required_version = "= 1.15.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.21.0"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
}

# The parent zone delegates this subdomain with NS records that point at this
# zone's name servers. Recreating the zone changes them unless a reusable
# delegation set (bootstrap stack) is supplied.
resource "aws_route53_zone" "assessment" {
  name              = var.domain_name
  comment           = "AWS DevOps practical assessment delegated subdomain"
  delegation_set_id = var.delegation_set_id

  tags = {
    Project   = "aws-devops-practical-assessment"
    ManagedBy = "Terraform"
  }
}

output "hosted_zone_id" {
  value = aws_route53_zone.assessment.zone_id
}

output "name_servers" {
  value = aws_route53_zone.assessment.name_servers
}

output "domain_name" {
  value = aws_route53_zone.assessment.name
}
