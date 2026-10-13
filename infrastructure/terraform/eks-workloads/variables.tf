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
  type = string
}

variable "eks_state_key" {
  type    = string
  default = "eks/terraform.tfstate"
}

variable "cicd_state_key" {
  type    = string
  default = "cicd/terraform.tfstate"
}

variable "route53_state_key" {
  type    = string
  default = "route53/terraform.tfstate"
}

variable "python_image_tag" {
  description = "Tag in the cicd ECR repository. CodeBuild pushes <commit-sha> and latest on every push."
  type        = string
  default     = "latest"
}

variable "python_time_on_karpenter" {
  description = "Schedule the Python workload on the Karpenter NodePool (brief §2: Karpenter must launch t3.medium for workload pods). Set false on an AWS Free account plan, which rejects t3.medium launches; the pods then stay on the system node group."
  type        = bool
  default     = true
}

variable "eks_record_name" {
  description = "Label for the EKS application record inside the route53 stack's domain."
  type        = string
  default     = "eks"
}

variable "adopt_existing_resources" {
  description = "Import Kubernetes objects and the DNS record created outside Terraform (live environment). Leave false for a fresh deployment."
  type        = bool
  default     = false
}
