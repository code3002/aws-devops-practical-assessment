terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-south-1"
}

resource "aws_route53_zone" "assessment" {
  name    = "aws.rahulbagal.tech"
  comment = "AWS DevOps practical assessment delegated subdomain"

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
