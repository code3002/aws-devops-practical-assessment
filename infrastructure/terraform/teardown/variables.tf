variable "TTL_HOURS" {
  description = "Hours after DEPLOYMENT_STARTED_AT at which everything is destroyed (brief §6, default 48)."
  type        = number
  default     = 48
  nullable    = false

  validation {
    condition     = var.TTL_HOURS > 0 && floor(var.TTL_HOURS) == var.TTL_HOURS
    error_message = "TTL_HOURS must be a positive whole number of hours."
  }
}

variable "DEPLOYMENT_STARTED_AT" {
  description = "Fixed environment start instant in UTC (YYYY-MM-DDTHH:MM:SSZ), e.g. the repository access grant. Never recompute; extend with TTL_HOURS instead."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.DEPLOYMENT_STARTED_AT)) && can(formatdate("YYYY-MM-DD", var.DEPLOYMENT_STARTED_AT))
    error_message = "DEPLOYMENT_STARTED_AT must be a valid UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format."
  }
}

variable "TEARDOWN_ENABLED" {
  description = "Schedule state. false cancels the automatic teardown (schedule DISABLED) without deleting anything."
  type        = bool
  default     = false
  nullable    = false
}

variable "EXECUTION_MODE" {
  description = "DESTROY runs terraform destroy for every stack in order. PREFLIGHT_ONLY checks identity/state and plans the destroy without changing anything."
  type        = string
  default     = "PREFLIGHT_ONLY"
  nullable    = false

  validation {
    condition     = contains(["PREFLIGHT_ONLY", "DESTROY"], var.EXECUTION_MODE)
    error_message = "EXECUTION_MODE must be PREFLIGHT_ONLY or DESTROY."
  }
}

variable "AWS_ACCOUNT_ID" {
  description = "Intended account; provider and executor refuse any other."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.AWS_ACCOUNT_ID))
    error_message = "AWS_ACCOUNT_ID must contain exactly 12 digits."
  }
}

variable "DEPLOYMENT_ID" {
  description = "Name of the teardown schedule, Lambda, CodeBuild project and roles. Do not change it to extend TTL."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.DEPLOYMENT_ID))
    error_message = "DEPLOYMENT_ID must be 3-40 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "EC2_DEPLOYMENT_ID" {
  description = "deployment_id of the ec2/cicd stacks; scopes the executor's IAM permissions."
  type        = string
  nullable    = false
}

variable "EKS_CLUSTER_NAME" {
  description = "EKS cluster name (<eks deployment_id>-eks); scopes the executor's IAM permissions."
  type        = string
  nullable    = false
}

variable "EXTRA_IAM_NAME_PREFIXES" {
  description = "Additional IAM role/policy name prefixes the executor may delete (e.g. adopted resources with legacy names)."
  type        = list(string)
  default     = []
}

variable "SOURCE_VERSION" {
  description = "CodeCommit branch or commit the executor checks out; must contain the Terraform code that matches the deployed state."
  type        = string
  default     = "refs/heads/main"
}

variable "CODECOMMIT_REPOSITORY" {
  type    = string
  default = "aws-devops-practical-assessment"
}

variable "BACKEND_BUCKET" {
  description = "Existing shared Terraform state bucket (retained after teardown)."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.BACKEND_BUCKET))
    error_message = "Provide the existing S3 bucket name."
  }
}

variable "LOCK_TABLE" {
  description = "Existing DynamoDB LockID table (retained after teardown)."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.LOCK_TABLE))
    error_message = "Provide a valid DynamoDB table name."
  }
}

variable "STATE_KEYS" {
  description = "State key of every stack the executor destroys."
  type = object({
    cicd          = string
    eks_workloads = string
    eks_addons    = string
    eks           = string
    route53       = string
    ec2           = string
  })
  default = {
    cicd          = "cicd/terraform.tfstate"
    eks_workloads = "eks-workloads/terraform.tfstate"
    eks_addons    = "eks-addons/terraform.tfstate"
    eks           = "eks/terraform.tfstate"
    route53       = "route53/terraform.tfstate"
    ec2           = "ec2/terraform.tfstate"
  }
  validation {
    condition     = length(distinct(values(var.STATE_KEYS))) == 6 && alltrue([for key in values(var.STATE_KEYS) : can(regex("^[A-Za-z0-9_-]+/terraform\\.tfstate$", key))])
    error_message = "Six distinct explicit <stack>/terraform.tfstate keys are required."
  }
}
