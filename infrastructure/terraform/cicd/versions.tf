terraform {
  required_version = "= 1.15.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.21.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      DeploymentId = var.deployment_id
      Project      = "aws-devops-practical-assessment"
      Component    = "cicd"
      ManagedBy    = "Terraform"
    }
  }
}
