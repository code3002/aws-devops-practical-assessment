provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = {
      Project   = "aws-devops-practical-assessment"
      Component = "bootstrap"
      ManagedBy = "Terraform"
    }
  }
}
