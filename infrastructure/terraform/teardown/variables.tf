variable "TTL_HOURS" {
  description = "Hours from the environment's recorded start time until cleanup is requested. This input alone schedules or destroys nothing."
  type        = number
  default     = 48
  nullable    = false

  validation {
    condition     = var.TTL_HOURS > 0 && floor(var.TTL_HOURS) == var.TTL_HOURS
    error_message = "TTL_HOURS must be a positive whole number of hours."
  }
}

variable "DEPLOYMENT_STARTED_AT" {
  description = "Fixed environment start instant in UTC (YYYY-MM-DDTHH:MM:SSZ). Set once in retained inputs; never recompute during routine operations."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.DEPLOYMENT_STARTED_AT)) && can(formatdate("YYYY-MM-DD", var.DEPLOYMENT_STARTED_AT))
    error_message = "DEPLOYMENT_STARTED_AT must be a valid UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format."
  }
}

variable "TEARDOWN_ENABLED" {
  description = "Intentional cancellation switch. A future schedule must map false to DISABLED, not delete workload resources."
  type        = bool
  default     = false
  nullable    = false
}

variable "AWS_ACCOUNT_ID" {
  description = "Intended account; provider restricts operations to this account."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.AWS_ACCOUNT_ID))
    error_message = "AWS_ACCOUNT_ID must contain exactly 12 digits."
  }
}

variable "SOURCE_COMMIT_SHA" {
  description = "Reviewed immutable CodeCommit commit containing the executor scripts; branch names and tags are forbidden."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.SOURCE_COMMIT_SHA))
    error_message = "SOURCE_COMMIT_SHA must be a full lowercase 40-character commit SHA."
  }
}
variable "BACKEND_BUCKET" {
  description = "Existing shared Terraform state bucket; this stack does not create or migrate it."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.BACKEND_BUCKET))
    error_message = "Provide the existing S3 bucket name."
  }
}
variable "LOCK_TABLE" {
  description = "Existing DynamoDB LockID table, shared by the four state keys."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.LOCK_TABLE))
    error_message = "Provide a valid DynamoDB table name."
  }
}
variable "STATE_KEYS" {
  description = "Exact approved default-workspace state keys; no wildcard access or non-default workspaces."
  type        = object({ bootstrap = string, teardown = string, ec2 = string, eks = string })
  default = {
    bootstrap = "bootstrap/terraform.tfstate"
    teardown  = "teardown/terraform.tfstate"
    ec2       = "ec2/terraform.tfstate"
    eks       = "eks/terraform.tfstate"
  }
  nullable = false
  validation {
    condition     = length(distinct(values(var.STATE_KEYS))) == 4 && alltrue([for key in values(var.STATE_KEYS) : can(regex("^[A-Za-z0-9_-]+/terraform\\.tfstate$", key))])
    error_message = "Four distinct explicit <stack>/terraform.tfstate keys are required."
  }
}

variable "DEPLOYMENT_ID" {
  description = "Unique retained assessment name, used for resource names and tags. Do not change it to extend TTL."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.DEPLOYMENT_ID))
    error_message = "DEPLOYMENT_ID must be 3-40 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "EC2_INSTANCE_ID" {
  description = "Exact assessment EC2 instance ID when provisioned. Null is allowed while this foundation is preflight-only."
  type        = string
  default     = null
  validation {
    condition     = var.EC2_INSTANCE_ID == null ? true : can(regex("^i-([0-9a-f]{8}|[0-9a-f]{17})$", var.EC2_INSTANCE_ID))
    error_message = "Provide an exact EC2 instance ID, not a wildcard or name."
  }
}

variable "EKS_CLUSTER_NAME" {
  description = "Exact assessment EKS cluster name when provisioned. Null is allowed while this foundation is preflight-only."
  type        = string
  default     = null
  validation {
    condition     = var.EKS_CLUSTER_NAME == null ? true : can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$", var.EKS_CLUSTER_NAME))
    error_message = "Provide an exact EKS cluster name, not a wildcard."
  }
}
