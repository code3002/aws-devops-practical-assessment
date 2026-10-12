terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
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
