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

variable "lbc_chart_version" {
  description = "eks-charts aws-load-balancer-controller chart version."
  type        = string
}

variable "karpenter_chart_version" {
  description = "oci://public.ecr.aws/karpenter/karpenter chart version."
  type        = string
}

variable "strimzi_chart_version" {
  description = "oci://quay.io/strimzi-helm/strimzi-kafka-operator chart version."
  type        = string
  default     = "1.2.0"
}

variable "adopt_existing_resources" {
  description = "Import Helm releases and CRDs that were installed outside Terraform (live environment). Leave false for a fresh deployment."
  type        = bool
  default     = false
}
