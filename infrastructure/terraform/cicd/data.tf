data "terraform_remote_state" "ec2" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = var.ec2_state_key
    region = var.aws_region
  }
}

locals {
  ec2_instance_id        = data.terraform_remote_state.ec2.outputs.instance_id
  artifact_bucket        = data.terraform_remote_state.ec2.outputs.artifact_bucket
  deployment_document    = data.terraform_remote_state.ec2.outputs.deployment_document_name
  database_host          = data.terraform_remote_state.ec2.outputs.database_address
  admin_secret_arn       = data.terraform_remote_state.ec2.outputs.database_secret_arn
  application_secret_arn = data.terraform_remote_state.ec2.outputs.application_secret_arn
}
