variable "aws_region" {
  type    = string
  default = "ap-south-1"
  validation {
    condition     = var.aws_region == "ap-south-1"
    error_message = "This assessment stack must use ap-south-1."
  }
}

variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the verified 12-digit AWS account ID."
  }
}

variable "state_bucket" {
  description = "Shared Terraform state bucket (read for EC2 ALB outputs)."
  type        = string
}

variable "ec2_state_key" {
  type    = string
  default = "ec2/terraform.tfstate"
}

variable "domain_name" {
  description = "Hosted zone to create, delegated from the parent domain with NS records."
  type        = string
  default     = "aws.rahulbagal.tech"
}

variable "app_record_name" {
  description = "Label for the EC2 application record inside domain_name."
  type        = string
  default     = "app"
}

variable "delegation_set_id" {
  description = "Optional reusable delegation set (bootstrap output) so a recreated zone keeps the same name servers. Changing it on an existing zone replaces the zone."
  type        = string
  default     = null
}
