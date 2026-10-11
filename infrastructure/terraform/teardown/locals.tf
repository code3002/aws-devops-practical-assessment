locals {
  destroy_project_name = "${var.DEPLOYMENT_ID}-destroy"
  destroy_project_arn  = "arn:aws:codebuild:ap-south-1:${var.AWS_ACCOUNT_ID}:project/${local.destroy_project_name}"
  deployment_tags = {
    DeploymentId = var.DEPLOYMENT_ID
    ManagedBy    = "Terraform"
    Project      = "aws-devops-practical-assessment"
  }
}
