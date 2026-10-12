locals {
  deadline_check_at = plantimestamp()
  schedule_configuration = {
    schedule_expression          = "at(${formatdate("YYYY-MM-DD'T'hh:mm:ss", local.teardown_expires_at)})"
    schedule_expression_timezone = "UTC"
    flexible_time_window         = { mode = "OFF" }
    state                        = var.TEARDOWN_ENABLED ? "ENABLED" : "DISABLED"
  }
}

output "schedule_configuration" {
  description = "Validated configuration used by the Scheduler resource."
  value       = local.schedule_configuration

  precondition {
    condition     = !var.TEARDOWN_ENABLED || timecmp(local.teardown_expires_at, local.deadline_check_at) > 0
    error_message = "An enabled teardown deadline must be strictly in the future. Extend TTL intentionally or disable teardown; the start time will not be reset."
  }
  precondition {
    condition     = var.EXECUTION_MODE == "PREFLIGHT_ONLY" || (var.TEARDOWN_ENABLED && var.FULL_DESTROY_ENABLED && var.FULL_DESTROY_IAM_READY && var.EKS_CLUSTER_NAME != null && var.EKS_VPC_ID != null && length(var.EKS_PRIVATE_SUBNET_IDS) == 2 && var.EKS_KUBERNETES_VERSION != null && length(var.EKS_CLUSTER_PUBLIC_ACCESS_CIDRS) > 0 && var.EKS_NODE_INSTANCE_TYPE != null && var.EKS_NODE_DESIRED_SIZE != null)
    error_message = "DESTROY_FULL_STACK requires TEARDOWN_ENABLED, FULL_DESTROY_ENABLED, reviewed IAM readiness, and complete EKS inputs."
  }
}
