variable "aws_region" {
  type    = string
  default = "ap-south-1"
  validation {
    condition     = var.aws_region == "ap-south-1"
    error_message = "Assessment region must be ap-south-1."
  }
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Use a verified 12-digit AWS account ID."
  }
}
variable "deployment_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.deployment_id))
    error_message = "Use 3-40 lowercase letters, numbers or hyphens."
  }
}
variable "vpc_id" {
  type = string
}
variable "private_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.private_subnet_ids) == 2 && length(distinct(var.private_subnet_ids)) == 2
    error_message = "Supply exactly two distinct private subnet IDs."
  }
}
variable "kubernetes_version" {
  description = "Explicitly reviewed EKS-supported Kubernetes version."
  type        = string
  validation {
    condition     = can(regex("^1[.][0-9]+$", var.kubernetes_version))
    error_message = "Use a version such as 1.xx."
  }
}
variable "cluster_public_access_cidrs" {
  description = "Your verified public IPv4 /32, not 0.0.0.0/0."
  type        = list(string)
  validation {
    condition     = length(var.cluster_public_access_cidrs) > 0 && alltrue([for c in var.cluster_public_access_cidrs : can(cidrnetmask(c)) && c != "0.0.0.0/0"])
    error_message = "Provide restricted valid IPv4 CIDRs."
  }
}
variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}
variable "node_desired_size" {
  type    = number
  default = 2
}
