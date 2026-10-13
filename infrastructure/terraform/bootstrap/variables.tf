variable "aws_region" {
  description = "Assessment deployment region."
  type        = string
  default     = "ap-south-1"
  validation {
    condition     = var.aws_region == "ap-south-1"
    error_message = "This assessment bootstrap targets ap-south-1."
  }
}
variable "expected_account_id" {
  description = "Privately confirmed AWS account; provider refuses other accounts."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the confirmed 12-digit account ID via private input."
  }
}
variable "repository_name" {
  description = "Name of the CodeCommit mirror repository."
  type        = string
  default     = "aws-devops-practical-assessment"
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,100}$", var.repository_name))
    error_message = "Use 1-100 CodeCommit-compatible name characters."
  }
}
variable "state_bucket_name" {
  description = "Globally unique S3 state bucket, without account IDs or secrets."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "Use 3-63 lowercase letters/digits/hyphens, starting with a letter and ending alphanumeric."
  }
}
variable "lock_table_name" {
  description = "Shared DynamoDB Terraform lock table."
  type        = string
  default     = "aws-devops-assessment-locks"
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.lock_table_name))
    error_message = "Use a DynamoDB-compatible table name of 3-255 characters."
  }
}
variable "create_delegation_set" {
  description = "Create a Route 53 reusable delegation set so the assessment hosted zone keeps the same name servers when it is destroyed and recreated."
  type        = bool
  default     = false
}
