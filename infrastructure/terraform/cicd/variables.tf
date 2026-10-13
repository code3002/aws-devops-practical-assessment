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

variable "deployment_id" {
  description = "Same deployment_id as the EC2 stack; names the build project and rule."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.deployment_id))
    error_message = "Use 3-40 lowercase letters, digits or hyphens, starting with a letter."
  }
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

variable "python_ecr_repository_name" {
  description = "ECR repository for the EKS Python image; CodeBuild pushes <commit-sha> and latest tags."
  type        = string
  default     = "eks-python-time"
}

variable "adopt_existing_resources" {
  description = "Import resources that were created outside Terraform (the live environment). Leave false for a fresh deployment."
  type        = bool
  default     = false
}

variable "source_branch" {
  description = "CodeCommit branch this pipeline builds and deploys. Production uses main; a staging copy can track a feature branch so it never reacts to main pushes."
  type        = string
  default     = "main"
}
