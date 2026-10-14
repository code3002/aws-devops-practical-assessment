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

variable "adopt_existing_resources" {
  description = "Import add-on IAM resources that were created outside Terraform (the live environment). Leave false for a fresh deployment."
  type        = bool
  default     = false
}

variable "lbc_iam_role_name" {
  description = "AWS Load Balancer Controller IAM role name. Null derives <cluster>-alb-controller."
  type        = string
  default     = null
}

variable "lbc_iam_policy_name" {
  description = "AWS Load Balancer Controller IAM policy name. Null derives <cluster>-alb-controller."
  type        = string
  default     = null
}

variable "existing_lbc_pod_identity_association_id" {
  description = "Adoption only: ID (a-xxxxxxxx) of the Load Balancer Controller Pod Identity association created outside Terraform."
  type        = string
  default     = null
}

variable "reviewer_principal_arns" {
  description = "IAM role/user ARNs that receive kubectl access through EKS access entries (brief §2 deliverable)."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for arn in var.reviewer_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+$", arn))])
    error_message = "Use IAM role or user ARNs."
  }
}

variable "reviewer_access_policy_arn" {
  description = "EKS access policy for reviewers. Cluster admin lets the reviewer run the Kafka verification (kubectl exec)."
  type        = string
  default     = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
}

variable "teardown_role_arn" {
  description = "Teardown executor role (teardown stack output destroy_role_arn). Gets cluster-admin so it can delete Kubernetes-created AWS resources before EKS is destroyed."
  type        = string
  default     = null
}

variable "jump_security_group_id" {
  description = "Security group of the reviewer jump server (ec2 output jump_security_group_id); allowed to reach the private API endpoint on 443."
  type        = string
  default     = null
}
