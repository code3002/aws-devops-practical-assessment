provider "aws" {
  region              = "ap-south-1"
  allowed_account_ids = [var.AWS_ACCOUNT_ID]
  default_tags {
    tags = local.deployment_tags
  }
}
