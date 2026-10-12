variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "expected_account_id" {
  type = string
}

variable "deployment_id" {
  type = string
}

variable "state_bucket" {
  type = string
}

variable "ec2_state_key" {
  type    = string
  default = "ec2/terraform.tfstate"
}

variable "codecommit_repository_name" {
  type    = string
  default = "aws-devops-practical-assessment"
}
