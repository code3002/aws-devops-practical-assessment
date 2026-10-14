variable "aws_region" {
  type     = string
  default  = "ap-south-1"
  nullable = false
  validation {
    condition     = var.aws_region == "ap-south-1"
    error_message = "This assessment stack must use ap-south-1."
  }
}
variable "expected_account_id" {
  type     = string
  nullable = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the verified 12-digit AWS account ID."
  }
}
variable "deployment_id" {
  type     = string
  nullable = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.deployment_id))
    error_message = "Use 3-40 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "vpc_cidr" {
  type     = string
  default  = "10.10.0.0/16"
  nullable = false
  validation {
    condition     = var.vpc_cidr == "10.10.0.0/16"
    error_message = "Use the approved VPC CIDR 10.10.0.0/16; subnet ranges derive from it."
  }
}
variable "reviewer_ssh_cidr" {
  type     = string
  nullable = false
  validation {
    condition     = can(cidrnetmask(var.reviewer_ssh_cidr)) && try(tonumber(split("/", var.reviewer_ssh_cidr)[1]) >= 24 && tonumber(split("/", var.reviewer_ssh_cidr)[1]) <= 32, false)
    error_message = "Supply a reviewer IPv4 CIDR with prefix /24 through /32; unrestricted SSH is forbidden."
  }
}

variable "reviewed_ami_id" {
  description = "Reviewed Amazon-owned AL2023 x86_64 AMI ID in this region; never automatically follow latest."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^ami-[0-9a-f]{17}$", var.reviewed_ami_id))
    error_message = "Supply a reviewed full AMI ID."
  }
}
variable "postgres_version" {
  description = "Explicit major.minor PostgreSQL version verified as orderable with db.t4g.micro and gp3 in ap-south-1."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[1-9][0-9]\\.[0-9]+$", var.postgres_version))
    error_message = "Supply an explicit PostgreSQL major.minor version; regional support must be checked before deployment."
  }
}
variable "ssh_key_name" {
  description = "Optional existing reviewer key-pair name. Null means SSH authentication is not configured; use SSM."
  type        = string
  default     = null
  validation {
    condition     = var.ssh_key_name == null ? true : length(trimspace(var.ssh_key_name)) > 0
    error_message = "Key name must be null or nonempty."
  }
}

variable "artifact_bucket" {
  description = "Existing approved private versioned artifact bucket; null creates a dedicated disposable bucket. Never use the state bucket."
  type        = string
  default     = null
  validation {
    condition     = var.artifact_bucket == null ? true : can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.artifact_bucket))
    error_message = "Supply an approved bucket name or null."
  }
}
variable "app_secret_arn" {
  description = "Existing application secret in this account/region; null creates metadata only. Populate its value outside Terraform."
  type        = string
  default     = null
  validation {
    condition     = var.app_secret_arn == null ? true : can(regex("^arn:aws:secretsmanager:ap-south-1:${var.expected_account_id}:secret:[A-Za-z0-9/_+=.@-]+$", var.app_secret_arn))
    error_message = "Use the exact application secret ARN in the expected account and region."
  }
}

variable "ssm_document_name" {
  description = "Optional SSM deployment document name override (must not start with aws, amazon or amzn)."
  type        = string
  default     = null
  validation {
    condition     = var.ssm_document_name == null ? true : can(regex("^[a-zA-Z0-9_.-]{3,128}$", var.ssm_document_name)) && !can(regex("^(?i)(aws|amazon|amzn)", var.ssm_document_name))
    error_message = "Use 3-128 letters, digits, '_', '-' or '.', not starting with aws, amazon or amzn (reserved by SSM)."
  }
}

variable "enable_reviewer_ssh" {
  description = "Open TCP 22 on the EC2 security group to reviewer_ssh_cidr only. SSM Session Manager is the default access path."
  type        = bool
  default     = false
}

variable "manage_application_secret_value" {
  description = "Generate and store the application database credential during apply as a write-only value (never stored in state). Keep false when the secret was already populated, or the running application loses database access."
  type        = bool
  default     = false
}

variable "create_reviewer_access" {
  description = "Create the reviewer IAM user and read-only role (console, CLI, SSM session to the app instance; add the role ARN to eks reviewer_principal_arns for kubectl)."
  type        = bool
  default     = true
}

variable "create_jump_server" {
  description = "Create the private jump server and EC2 Instance Connect Endpoint used by reviewers (kubectl, Kafka and Prometheus checks)."
  type        = bool
  default     = true
}

variable "jump_eks_cluster_name" {
  description = "EKS cluster the jump server configures kubectl for (<eks deployment_id>-eks). Empty skips kubeconfig."
  type        = string
  default     = ""
}
