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

variable "EXECUTION_MODE" {
  description = "CodeBuild cleanup mode. Full destruction is disabled unless every explicit safety gate is enabled."
  type        = string
  default     = "PREFLIGHT_ONLY"
  nullable    = false

  validation {
    condition     = contains(["PREFLIGHT_ONLY", "DESTROY_FULL_STACK"], var.EXECUTION_MODE)
    error_message = "EXECUTION_MODE must be PREFLIGHT_ONLY or DESTROY_FULL_STACK."
  }
}

variable "FULL_DESTROY_ENABLED" {
  description = "Explicit second switch for whole-stack destruction; defaults off."
  type        = bool
  default     = false
  nullable    = false
}

variable "FULL_DESTROY_IAM_READY" {
  description = "Reviewed external confirmation that the executor role has exact destroy permissions. This stack intentionally grants read-only permissions."
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

variable "EKS_VPC_ID" {
  description = "Exact VPC ID retained for reconstructing EKS destroy inputs. Required for full mode."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.EKS_VPC_ID == null ? true : can(regex("^vpc-[0-9a-f]{8,17}$", var.EKS_VPC_ID))
    error_message = "EKS_VPC_ID must be an exact VPC ID."
  }
}

variable "EKS_PRIVATE_SUBNET_IDS" {
  description = "Exactly two private subnet IDs retained for reconstructing EKS destroy inputs."
  type        = list(string)
  default     = []
  nullable    = false
  validation {
    condition     = length(var.EKS_PRIVATE_SUBNET_IDS) == 0 || (length(var.EKS_PRIVATE_SUBNET_IDS) == 2 && length(distinct(var.EKS_PRIVATE_SUBNET_IDS)) == 2 && alltrue([for id in var.EKS_PRIVATE_SUBNET_IDS : can(regex("^subnet-[0-9a-f]{8,17}$", id))]))
    error_message = "Provide exactly two distinct EKS private subnet IDs."
  }
}

variable "EKS_KUBERNETES_VERSION" {
  description = "EKS Kubernetes version retained for reconstructing destroy inputs."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.EKS_KUBERNETES_VERSION == null ? true : can(regex("^1[.][0-9]+$", var.EKS_KUBERNETES_VERSION))
    error_message = "EKS_KUBERNETES_VERSION must look like 1.xx."
  }
}

variable "EKS_CLUSTER_PUBLIC_ACCESS_CIDRS" {
  description = "Restricted public CIDRs retained for reconstructing EKS destroy inputs."
  type        = list(string)
  default     = []
  nullable    = false
  validation {
    condition     = length(var.EKS_CLUSTER_PUBLIC_ACCESS_CIDRS) == 0 || alltrue([for cidr in var.EKS_CLUSTER_PUBLIC_ACCESS_CIDRS : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "EKS public access CIDRs must be valid and restricted."
  }
}

variable "EKS_NODE_INSTANCE_TYPE" {
  description = "EKS system node instance type retained for reconstructing destroy inputs."
  type        = string
  default     = null
  nullable    = true
}

variable "EKS_NODE_DESIRED_SIZE" {
  description = "EKS system node desired size retained for reconstructing destroy inputs."
  type        = number
  default     = null
  nullable    = true
  validation {
    condition     = var.EKS_NODE_DESIRED_SIZE == null ? true : var.EKS_NODE_DESIRED_SIZE > 0 && floor(var.EKS_NODE_DESIRED_SIZE) == var.EKS_NODE_DESIRED_SIZE
    error_message = "EKS_NODE_DESIRED_SIZE must be a positive whole number."
  }
}
