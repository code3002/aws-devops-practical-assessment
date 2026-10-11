provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = {
      DeploymentId = var.deployment_id
      Project      = "aws-devops-practical-assessment"
      Component    = "ec2"
      ManagedBy    = "Terraform"
    }
  }
}
